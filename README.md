# AI review event service · #2072

A small, append-only event store that unifies how AI tools in the member-space
platform report drafts and human review outcomes. It is the data source for
adoption rate, edit magnitude and rejection-reason analytics.

- Scope: event specification, reject-reason dictionary seed, SQLAlchemy model,
  Alembic migration, HTTP endpoint and in-process Python function.
- Stack: Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16.
  SQLite is supported for fast local tests.
- No third-party analytics SDK and no draft/final full text is stored.

## Layout

| Path | Purpose |
| --- | --- |
| app/eval/constants.py | Event types, actions, dictionary codes, limits |
| app/eval/models.py | ai_review_event and ai_reject_reason models |
| app/eval/validators.py | Pure field validation and normalization |
| app/eval/service.py | Batch ingestion, idempotency, expiry job |
| app/eval/api.py | POST /api/eval/review-events |
| alembic/versions/0001_ai_review_events.py | Schema, 17 CHECK constraints, partial unique indexes, dictionary seed |
| docs/EVENT-SPEC.md | Event contract, state machine, metric definitions |
| docs/REJECT-REASONS.md | Reject-reason dictionary |
| scripts/ | Acceptance, PostgreSQL evidence, DDL export, mutation drill |
| tests/ | 62 pytest tests (migration, constraints, service, HTTP) |

## Quick start

```bash
python -m pip install -r requirements.txt
export REVIEW_EVENT_DB_URL=postgresql+psycopg2://postgres@127.0.0.1:55432/clawhunt_2072
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

SQLite quick start (the tests use this by default):

```bash
export REVIEW_EVENT_DB_URL=sqlite:///./review_events.db
python -m alembic upgrade head
python -m pytest -q tests
```

## HTTP contract

`POST /api/eval/review-events`

Headers: `X-Org-Id` (UUID, optional, defaults to the all-zero tenant) and
`X-Actor-Id` (UUID, optional, stored as `created_by`).

Body: `{"events": [...]}` or a bare JSON array. A batch contains 1-100 events.
The array is validated as a whole; one invalid event rejects the batch.

Success (HTTP 200):

```json
{
  "created": 2,
  "duplicates": 1,
  "received": 3,
  "items": [
    {"event_id": "…", "status": "created"},
    {"event_id": "…", "status": "duplicate"},
    {"event_id": "…", "status": "created"}
  ]
}
```

Errors are always `{"code": "...", "message": "..."}`:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 422 | BATCH_EMPTY / BATCH_TOO_LARGE | Empty batch or more than 100 events |
| 422 | EVENT_FIELD_INVALID | Wrong type, missing required field, unknown field or invalid hash |
| 422 | DRAFT_NOT_FOUND | Review event before the draft creation event |
| 422 | EVENT_BEFORE_DRAFT_CREATED | Event timestamp is earlier than the creation event |
| 422 | EVENT_BEFORE_REVIEW_OPENED | Terminal event timestamp is earlier than the latest review_opened |
| 422 | DRAFT_NOT_EXPIRED | draft_expired not more than 7 days after creation |
| 409 | DRAFT_ALREADY_EXISTS | More than one creation event for a draft |
| 422 | REJECT_REASON_INVALID | Unknown or inactive reject_reason_code |
| 422 | OTHER_NOTE_REQUIRED | `other` without a non-empty note |
| 422 | REQUEST_INVALID / ORG_INVALID / ACTOR_INVALID | Malformed JSON or identifier header |
| 409 | DRAFT_ALREADY_TERMINAL | A draft already has review_submitted or draft_expired |
| 409 | EVENT_ID_PAYLOAD_MISMATCH | Same event_id reused with a different payload |
| 409 | EVENT_ID_CONFLICT | Same event_id already belongs to another tenant |

A batch is atomic: a 422/409 leaves no event from that request in the database.

### Idempotency

`event_id` is the primary key. Re-posting the same event_id with the same
payload returns `status: "duplicate"` and writes nothing. Re-posting it with a
different payload is a 409. Duplicate event_ids inside a single batch are
collapsed the same way.

### Ordering

Events in a batch are ordered by type (creation, opened, terminal) and then by
`occurred_at`, so callers may send the three events of one review in any order.
Timestamps still have to be logically consistent: `review_opened` must not be
earlier than draft creation, `review_submitted` must be strictly later, a
terminal event must not be earlier than the latest `review_opened`, and
`draft_expired` must be more than 7 days after creation.

## Python function

```python
from app.eval.service import submit_review_events, expire_stale_drafts

result = submit_review_events(session, org_id, events, actor_id=None)
expired_event_ids = expire_stale_drafts(session, org_id, now=None)
```

Both return domain results and raise `ReviewEventError` with `code`,
`message` and `status_code`; `expire_stale_drafts` uses a deterministic UUID v5
per draft, so a retry cannot create a second expiry event.

## Data model

`ai_review_event` stores references and hashes, never the draft or final text.
It has the unified columns `id, org_id, site_id, created_at, created_by,
updated_at, deleted_at`, plus event fields.

- 17 CHECK constraints enforce event/field combinations and ranges.
- `uq_ai_review_event_draft_created`: one live creation event per (org, draft).
- `uq_ai_review_event_draft_terminal`: one live terminal event per (org, draft).
  Both partial indexes only apply to `deleted_at IS NULL`.
- `ix_ai_review_event_org_type_time` supports time-window adoption metrics.
- `ix_ai_review_event_org_draft_time` supports draft timelines.

`ai_reject_reason` is a global, deterministic dictionary seed (all-zero org id)
migration. Application code must be redeployed if a new code is added.

## Expiry job

Run hourly from any scheduler:

```bash
python -c "from app.db import create_db_engine; \
from sqlalchemy.orm import sessionmaker; \
from app.eval.service import expire_stale_drafts; \
import uuid; \
s=sessionmaker(bind=create_db_engine())(); \
print(expire_stale_drafts(s, uuid.UUID(int=0)))"
```

The job only emits events; it does not delete drafts. A draft with an existing
terminal event is skipped.

## Metrics

| Metric | Definition |
| --- | --- |
| Adoption rate | share of drafts with final action in (adopted_as_is, adopted_with_edits) |
| Edit magnitude | count of review_submitted with action=adopted_with_edits over all reviews |
| Rejection reason | grouped reject_reason_code on action=rejected |
| Review latency | `review_submitted.occurred_at - ai_draft_created.occurred_at`, and `review_seconds` when present |
| Expiry rate | drafts with draft_expired and no review_submitted |

## Tests and evidence

```bash
python -m pytest -q tests            # 62 passed (SQLite)
python scripts/run_acceptance.py     # AC1-AC4 + full regression
python scripts/export_pg_ddl.py      # artifacts/schema-postgres.sql
python scripts/run_pg16_round.py --label round1
python scripts/reverse_drill.py      # 3/3 mutations detected
```

PostgreSQL evidence uses `clawhunt_2072` on `127.0.0.1:55432`; set
`PG_TEST_URL` and `PG_TEST_DB` to point elsewhere. The round script requires the
database to exist and the PostgreSQL `bin` directory in `PG_BIN`.

## Deliverables

- Event specification: `docs/EVENT-SPEC.md`
- Reject-reason dictionary: `docs/REJECT-REASONS.md` and migration seed
- Model and migration: `app/eval/models.py`,
  `alembic/versions/0001_ai_review_events.py`
- HTTP endpoint and Python function: `app/eval/api.py`,
  `app/eval/service.py`
- Tests: `tests/`; acceptance and PostgreSQL logs in `artifacts/`

## Security and data handling

All examples and test fixtures are synthetic. No reviewer identity beyond a
UUID, no member PII, no draft/final full text is stored. API authentication is
expected to be supplied by the platform gateway; this service accepts the
already-authenticated tenant and actor identifiers from headers.

## Known limitations

- The repository ships no production auth middleware; the gateway is expected
  to validate the API key and set `X-Org-Id` / `X-Actor-Id`.
- The expiry job is a Python function, not a bundled scheduler; deploy it with
  the platform's cron/worker.
- The dictionary is global (all-zero org) and changed by migration, not by an
  admin API.
- SQLite is supported for tests; PostgreSQL 16 is the reference database.
  The service starts an explicit SQLite transaction before its first savepoint
  so a failed batch cannot be partially committed by SQLite savepoint release.
