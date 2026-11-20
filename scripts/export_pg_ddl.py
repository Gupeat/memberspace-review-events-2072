"""Render the PostgreSQL DDL for the review-event migration offline."""
from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "artifacts" / "schema-postgres.sql"
PG_URL = os.environ.get(
    "PG_DATABASE_URL",
    "postgresql+psycopg2://postgres@127.0.0.1:55432/clawhunt_2072",
)
MARKERS = (
    "CREATE TABLE ai_reject_reason",
    "CREATE TABLE ai_review_event",
    "CHECK (event_type IN",
    "CHECK (action IS NULL OR action IN",
    "CHECK (reject_reason_code IS NULL OR reject_reason_code IN",
    "CHECK (event_type <> 'review_submitted'",
    "CHECK (reject_reason_code IS NULL OR reject_reason_code <> 'other'",
    "CREATE UNIQUE INDEX uq_ai_review_event_draft_created",
    "CREATE UNIQUE INDEX uq_ai_review_event_draft_terminal",
    "WHERE event_type = 'ai_draft_created' AND deleted_at IS NULL",
    "INSERT INTO ai_reject_reason",
    "CREATE TABLE alembic_version",
)


def main() -> int:
    os.environ["REVIEW_EVENT_DB_URL"] = PG_URL
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", PG_URL)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(config, "head", sql=True)
    ddl = buffer.getvalue()
    missing = [marker for marker in MARKERS if marker not in ddl]
    if missing:
        print("missing markers:", missing)
        return 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(ddl, encoding="utf-8")
    inserts = ddl.count("INSERT INTO ai_reject_reason")
    print(
        f"wrote {OUTPUT} bytes={len(ddl.encode('utf-8'))} "
        f"markers={len(MARKERS)} insert_statements={inserts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
