"""Mutation drill for #2072: break three guards and prove tests go red."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = "alembic/versions/0001_ai_review_events.py"
SERVICE = "app/eval/service.py"

MIGRATION_OTHER_CHECK = "\n".join(
    [
        "        sa.CheckConstraint(",
        '            "reject_reason_code IS NULL OR reject_reason_code <> \'other\' OR "',
        '            "(reject_reason_note IS NOT NULL AND length(trim(reject_reason_note)) > 0)",',
        '            name=op.f("ck_ai_review_event_other_requires_note"),',
        "        ),",
    ]
)
MIGRATION_OTHER_BROKEN = '        sa.CheckConstraint("1=1", name=op.f("ck_ai_review_event_other_requires_note")),'

TERMINAL_INDEX = "\n".join(
    [
        "    op.create_index(",
        '        "uq_ai_review_event_draft_terminal",',
        '        "ai_review_event",',
        '        ["org_id", "draft_id"],',
        "        unique=True,",
        '        postgresql_where=sa.text(',
        '            "event_type IN (\'review_submitted\',\'draft_expired\') AND deleted_at IS NULL"',
        "        ),",
        '        sqlite_where=sa.text(',
        '            "event_type IN (\'review_submitted\',\'draft_expired\') AND deleted_at IS NULL"',
        "        ),",
        "    )",
    ]
)
TERMINAL_INDEX_BROKEN = "    # terminal unique index removed by the mutation drill"

SERVICE_VALIDATE = "    _validate_dictionary(session, normalized)"
SERVICE_VALIDATE_BROKEN = "    pass  # dictionary validation removed by the mutation drill"

TARGETS = [
    (
        "other_requires_note CHECK removed",
        MIGRATION,
        MIGRATION_OTHER_CHECK,
        MIGRATION_OTHER_BROKEN,
        ["-m", "pytest", "-q", "tests/test_constraints.py::test_other_reason_requires_note"],
    ),
    (
        "terminal partial unique index removed",
        MIGRATION,
        TERMINAL_INDEX,
        TERMINAL_INDEX_BROKEN,
        ["-m", "pytest", "-q", "tests/test_constraints.py::test_second_terminal_event_is_rejected"],
    ),
    (
        "dictionary activation check removed",
        SERVICE,
        SERVICE_VALIDATE,
        SERVICE_VALIDATE_BROKEN,
        ["-m", "pytest", "-q", "tests/test_service.py::test_inactive_reason_is_rejected"],
    ),
]


def main() -> int:
    logs: list[str] = []
    detected = 0
    base_tmp = Path(tempfile.mkdtemp(prefix="review-events-drill-"))
    try:
        for index, (name, rel, old, new, args) in enumerate(TARGETS, start=1):
            target = base_tmp / f"mutant-{index}"
            shutil.copytree(
                REPO_ROOT,
                target,
                ignore=shutil.ignore_patterns(
                    "artifacts", "__pycache__", ".pytest_cache", "*.db", ".git"
                ),
            )
            path = target / rel
            text = path.read_text(encoding="utf-8")
            if old not in text:
                logs.append(f"{name}: MUTATION-NOT-APPLIED")
                continue
            path.write_text(text.replace(old, new), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, *args],
                cwd=str(target),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            hit = completed.returncode != 0
            detected += 1 if hit else 0
            logs.append(f"{name}: {'DETECTED' if hit else 'MISSED'} (exit {completed.returncode})")
            logs.append((completed.stdout + completed.stderr)[-1200:])
    finally:
        shutil.rmtree(base_tmp, ignore_errors=True)

    output = f"mutations={len(TARGETS)} detected={detected}\n" + "\n".join(logs)
    home = str(Path.home())
    output = output.replace(home, "<home>").replace(home.replace("\\", "/"), "<home>")
    output = output.replace(str(base_tmp), "<tmp>").replace(str(REPO_ROOT), "<repo>")
    output = output.replace("pytest-of-" + Path.home().name, "pytest-of-user")
    (REPO_ROOT / "artifacts" / "reverse-drill.log").write_text(output, encoding="utf-8")
    print(output)
    return 0 if detected == len(TARGETS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
