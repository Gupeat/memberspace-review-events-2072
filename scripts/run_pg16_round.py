"""Run one reproducible PostgreSQL 16 acceptance round for #2072."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PG_BIN = Path(
    os.environ.get(
        "PG_BIN",
        Path(os.environ.get("TEMP", ".")) / "clawhunt-pg16" / "pg" / "pgsql" / "bin",
    )
)
PSQL = PG_BIN / "psql.exe"
PG_URL = os.environ.get(
    "PG_TEST_URL", "postgresql+psycopg2://postgres@127.0.0.1:55432/clawhunt_2072"
)
PSQL_DB = os.environ.get("PG_TEST_DB", "clawhunt_2072")


def redact(text: str) -> str:
    text = text.replace(str(REPO_ROOT), "<repo>")
    text = text.replace(str(Path(os.environ.get("TEMP", ""))), "<tmp>")
    home = str(Path.home())
    text = text.replace(home, "<home>").replace(home.replace("\\", "/"), "<home>")
    text = text.replace("pytest-of-" + Path.home().name, "pytest-of-user")
    return text


def run(args: list[str], env: dict[str, str], timeout: int = 300) -> tuple[int, str]:
    completed = subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return completed.returncode, redact(completed.stdout + completed.stderr)


def psql(sql: str, env: dict[str, str]) -> tuple[int, str]:
    return run(
        [
            str(PSQL),
            "-h",
            "127.0.0.1",
            "-p",
            "55432",
            "-U",
            "postgres",
            "-d",
            PSQL_DB,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        env,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="round")
    args = parser.parse_args()

    out_dir = REPO_ROOT / "artifacts" / "pg16" / args.label
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = str(PG_BIN) + os.pathsep + env.get("PATH", "")
    env["REVIEW_EVENT_DB_URL"] = PG_URL
    env["PYTHONIOENCODING"] = "utf-8"

    steps: list[tuple[str, int, str]] = []

    def record(name: str, code: int, output: str) -> None:
        steps.append((name, code, output))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (out_dir / f"{len(steps)-1:02d}-{name}.log").write_text(
            f"# recorded_at {stamp}\n{output}", encoding="utf-8"
        )

    record("reset", *psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;", env))
    record("upgrade-head", *run([sys.executable, "-m", "alembic", "upgrade", "head"], env))
    record(
        "tables",
        *psql(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name;",
            env,
        ),
    )
    record(
        "columns",
        *psql(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name='ai_review_event' ORDER BY ordinal_position;",
            env,
        ),
    )
    record(
        "indexes",
        *psql(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='ai_review_event' ORDER BY indexname;",
            env,
        ),
    )
    record(
        "dictionary",
        *psql(
            "SELECT code, label_zh, requires_note, sort_order, active "
            "FROM ai_reject_reason ORDER BY sort_order;",
            env,
        ),
    )
    record(
        "pytest",
        *run(
            [sys.executable, "-m", "pytest", "-q", "tests"],
            {**env, "TEST_DATABASE_URL": PG_URL},
        ),
    )
    # The test fixture downgrades after every test, so restore head before
    # running the drift and downgrade checks.
    record("upgrade-after-tests", *run([sys.executable, "-m", "alembic", "upgrade", "head"], env))
    record("alembic-check", *run([sys.executable, "-m", "alembic", "check"], env))
    record("downgrade-minus-one", *run([sys.executable, "-m", "alembic", "downgrade", "-1"], env))
    record(
        "tables-absent-after-downgrade",
        *psql(
            "SELECT count(*) AS review_tables FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name IN ('ai_review_event','ai_reject_reason');",
            env,
        ),
    )
    record("upgrade-final", *run([sys.executable, "-m", "alembic", "upgrade", "head"], env))
    record(
        "tables-present-final",
        *psql(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name IN "
            "('ai_review_event','ai_reject_reason') ORDER BY table_name;",
            env,
        ),
    )
    record(
        "constraints",
        *psql(
            "SELECT count(*) AS check_constraints FROM pg_constraint "
            "WHERE conrelid='ai_review_event'::regclass AND contype='c';",
            env,
        ),
    )
    record(
        "partial-indexes",
        *psql(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='ai_review_event' "
            "AND indexname IN ('uq_ai_review_event_draft_created','uq_ai_review_event_draft_terminal') "
            "ORDER BY indexname;",
            env,
        ),
    )

    by_name = {name: (code, output) for name, code, output in steps}
    pytest_output = by_name["pytest"][1]
    passed_matches = re.findall(r"(\d+) passed", pytest_output)
    passed = int(passed_matches[-1]) if passed_matches else 0

    tables_ok = "ai_review_event" in by_name["tables"][1] and "ai_reject_reason" in by_name["tables"][1]
    final_ok = (
        "ai_review_event" in by_name["tables-present-final"][1]
        and "ai_reject_reason" in by_name["tables-present-final"][1]
    )
    check_ok = by_name["alembic-check"][0] == 0
    downgrade_empty = re.search(
        r"review_tables\s*\n[-+]+\n\s*0\b", by_name["tables-absent-after-downgrade"][1]
    ) is not None
    constraints_ok = re.search(
        r"check_constraints\s*\n[-+]+\n\s*17\b", by_name["constraints"][1]
    ) is not None
    dictionary_ok = all(
        code in by_name["dictionary"][1]
        for code in (
            "factual_error",
            "off_tone",
            "missing_info",
            "policy_violation",
            "duplicate",
            "not_needed",
            "other",
        )
    )
    partial_ok = (
        "uq_ai_review_event_draft_created" in by_name["partial-indexes"][1]
        and "uq_ai_review_event_draft_terminal" in by_name["partial-indexes"][1]
        and "deleted_at IS NULL" in by_name["partial-indexes"][1]
    )
    ok = (
        all(code == 0 for _, code, _ in steps)
        and tables_ok
        and final_ok
        and check_ok
        and downgrade_empty
        and constraints_ok
        and dictionary_ok
        and partial_ok
    )

    summary = [
        f"# PostgreSQL 16 acceptance · {args.label}",
        "",
        f"- PostgreSQL: 16.15 at 127.0.0.1:55432 / database {PSQL_DB}",
        f"- Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"- Tests: {passed} passed (SQLite + PostgreSQL)",
        f"- Alembic check: {'PASS' if check_ok else 'FAIL'}",
        f"- Tables after upgrade: {'PASS' if tables_ok else 'FAIL'}",
        f"- Tables after downgrade: {'PASS' if downgrade_empty else 'FAIL'}",
        f"- 17 CHECK constraints: {'PASS' if constraints_ok else 'FAIL'}",
        f"- 7 reject reasons: {'PASS' if dictionary_ok else 'FAIL'}",
        f"- Partial unique indexes: {'PASS' if partial_ok else 'FAIL'}",
        f"- Overall: {'PASS' if ok else 'FAIL'}",
        "",
        "## Steps",
        "",
        "| # | Step | Exit |",
        "| --- | --- | --- |",
    ]
    for index, (name, code, _) in enumerate(steps):
        summary.append(f"| {index} | {name} | {code} |")
    summary += [
        "",
        "## Evidence",
        "",
        "Logs 00-14 in this directory; the pytest log is copied to artifacts/pytest-pg16.log.",
        "",
    ]
    (out_dir / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")
    (REPO_ROOT / "artifacts").mkdir(exist_ok=True)
    (REPO_ROOT / "artifacts" / "pytest-pg16.log").write_text(pytest_output, encoding="utf-8")
    print("\n".join(summary))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
