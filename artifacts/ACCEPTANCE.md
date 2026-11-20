# Acceptance report · #2072

- Generated: 2026-11-20T18:44:27Z
- Database: SQLite quick regression; PostgreSQL 16 evidence in artifacts/pg16/
- Tests: 62 passed
- AC1 batch limit (101 rejected, 100 persisted): PASS
- AC2 event_id idempotency: PASS
- AC3 one terminal event per draft: PASS
- AC4 other reason requires a note: PASS
- Full regression: PASS

## Commands and results

| Step | Exit |
| --- | --- |
| AC1 migration upgrade head | 0 |
| AC1 101 events rejected / 100 persisted | 0 |
| AC1 Python function batch limit | 0 |
| AC2 event_id idempotency | 0 |
| AC2 service-level idempotency | 0 |
| AC3 second terminal returns 409 | 0 |
| AC4 other reject reason requires note | 0 |
| Full regression | 0 |

## Evidence

See artifacts/pytest.log, artifacts/schema-postgres.sql, and artifacts/pg16/round1|round2.
