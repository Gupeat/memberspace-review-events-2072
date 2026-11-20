"""Run the SQLite acceptance checks for #2072 and write evidence artifacts."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "artifacts"
PYTHON = sys.executable


def redact(text: str, tmp: str) -> str:
    text = text.replace(str(REPO_ROOT), "<repo>")
    text = text.replace(tmp, "<tmp>")
    home = str(Path.home())
    text = text.replace(home, "<home>").replace(home.replace("\\", "/"), "<home>")
    text = text.replace("pytest-of-" + Path.home().name, "pytest-of-user")
    return text


def run(args: list[str], env: dict[str, str], tmp: str) -> tuple[int, str]:
    completed = subprocess.run(
        args,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    return completed.returncode, redact(completed.stdout + completed.stderr, tmp)


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="review-events-acceptance-")
    db = "sqlite:///" + str(Path(tmp) / "acceptance.db")
    env = os.environ.copy()
    env["REVIEW_EVENT_DB_URL"] = db
    env["PYTHONIOENCODING"] = "utf-8"

    steps: list[dict[str, object]] = []
    logs: list[str] = []

    def step(name: str, args: list[str], extra_env: dict[str, str] | None = None) -> int:
        code, output = run(args, {**env, **(extra_env or {})}, tmp)
        steps.append({"name": name, "command": redact(" ".join(args), tmp), "exit": code})
        logs.append(f"$ {name}\n" + redact(" ".join(args), tmp) + "\n" + output)
        return code

    ac1 = [
        step("AC1 migration upgrade head", [PYTHON, "-m", "alembic", "upgrade", "head"]),
        step(
            "AC1 101 events rejected / 100 persisted",
            [PYTHON, "-m", "pytest", "-q", "tests/test_api.py", "-k", "ac1_"],
        ),
        step(
            "AC1 Python function batch limit",
            [PYTHON, "-m", "pytest", "-q", "tests/test_service.py", "-k", "ac1_"],
        ),
    ]
    ac2 = [
        step(
            "AC2 event_id idempotency",
            [PYTHON, "-m", "pytest", "-q", "tests/test_api.py", "-k", "ac2_"],
        ),
        step(
            "AC2 service-level idempotency",
            [PYTHON, "-m", "pytest", "-q", "tests/test_service.py", "-k", "ac2_"],
        ),
    ]
    ac3 = [
        step(
            "AC3 second terminal returns 409",
            [PYTHON, "-m", "pytest", "-q", "tests", "-k", "terminal"],
        ),
    ]
    ac4 = [
        step(
            "AC4 other reject reason requires note",
            [PYTHON, "-m", "pytest", "-q", "tests", "-k", "other"],
        ),
    ]
    full = step("Full regression", [PYTHON, "-m", "pytest", "-q", "tests"])

    combined = "\n".join(logs)
    (ARTIFACTS / "pytest.log").write_text(combined, encoding="utf-8")
    matches = re.findall(r"(\d+) passed", combined)
    passed = int(matches[-1]) if matches else 0
    ok = not any(ac1) and not any(ac2) and not any(ac3) and not any(ac4) and full == 0
    summary = {
        "ok": ok,
        "passed": passed,
        "ac1": not any(ac1),
        "ac2": not any(ac2),
        "ac3": not any(ac3),
        "ac4": not any(ac4),
        "full": full == 0,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "steps": steps,
    }

    lines = [
        "# Acceptance report · #2072",
        "",
        f"- Generated: {summary['generated_at']}",
        "- Database: SQLite quick regression; PostgreSQL 16 evidence in artifacts/pg16/",
        f"- Tests: {passed} passed",
        f"- AC1 batch limit (101 rejected, 100 persisted): {'PASS' if summary['ac1'] else 'FAIL'}",
        f"- AC2 event_id idempotency: {'PASS' if summary['ac2'] else 'FAIL'}",
        f"- AC3 one terminal event per draft: {'PASS' if summary['ac3'] else 'FAIL'}",
        f"- AC4 other reason requires a note: {'PASS' if summary['ac4'] else 'FAIL'}",
        f"- Full regression: {'PASS' if summary['full'] else 'FAIL'}",
        "",
        "## Commands and results",
        "",
        "| Step | Exit |",
        "| --- | --- |",
    ]
    for item in steps:
        lines.append(f"| {item['name']} | {item['exit']} |")
    lines += [
        "",
        "## Evidence",
        "",
        "See artifacts/pytest.log, artifacts/schema-postgres.sql, and artifacts/pg16/round1|round2.",
        "",
    ]
    (ARTIFACTS / "ACCEPTANCE.md").write_text("\n".join(lines), encoding="utf-8")
    (ARTIFACTS / "acceptance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
