# PostgreSQL 16 acceptance · round2

- PostgreSQL: 16.15 at 127.0.0.1:55432 / database clawhunt_2072
- Generated: 2026-11-20T18:39:44Z
- Tests: 62 passed (SQLite + PostgreSQL)
- Alembic check: PASS
- Tables after upgrade: PASS
- Tables after downgrade: PASS
- 17 CHECK constraints: PASS
- 7 reject reasons: PASS
- Partial unique indexes: PASS
- Overall: PASS

## Steps

| # | Step | Exit |
| --- | --- | --- |
| 0 | reset | 0 |
| 1 | upgrade-head | 0 |
| 2 | tables | 0 |
| 3 | columns | 0 |
| 4 | indexes | 0 |
| 5 | dictionary | 0 |
| 6 | pytest | 0 |
| 7 | upgrade-after-tests | 0 |
| 8 | alembic-check | 0 |
| 9 | downgrade-minus-one | 0 |
| 10 | tables-absent-after-downgrade | 0 |
| 11 | upgrade-final | 0 |
| 12 | tables-present-final | 0 |
| 13 | constraints | 0 |
| 14 | partial-indexes | 0 |

## Evidence

Logs 00-14 in this directory; the pytest log is copied to artifacts/pytest-pg16.log.
