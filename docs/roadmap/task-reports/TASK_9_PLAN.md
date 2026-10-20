# Task 9 — AUTH-A plan

Files touched (all owned, §6, except two test pins noted below): `alembic/versions/20261101000000_access_requests.py`,
`models/db_models.py` (append `AccessRequest` only), `api/plugins/access_requests.py`, `src/access/{__init__,rules,tokens,service}.py`,
`tests/api/test_access_requests.py`, `tests/authz_matrix.d/T9.yaml`, `docs/env/T9.md`, `.env.example` (append block).
Not owned, minimal edit forced by the new head: `tests/test_alembic_chain.py` and `tests/test_task28_migration.py` (head pins; same move Task 28 made).

Order: tests first (they fail on baseline: no table, no routes) -> model + migration -> tokens/rules -> service -> plugin -> matrix
fragment, docs, env block. Commands: the new suite, `tests/test_alembic_chain.py`, `tests/test_task28_migration.py`,
`tests/api/test_task29_admin_console.py`, `tests/test_startup_checks.py`, `alembic heads/check`, ruff.
