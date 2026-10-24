# R_L6 report (Postgres suite, load harness, CI hardening) - PARTIAL

Verdict: **PARTIAL**. Evidence is only what the user pasted on 2026-10-24.

## Postgres suite (`pytest tests -m postgres -rs -q`, Docker postgres:15.19, db `twingrid_test`)
- Run 1 (only `TWINGRID_TEST_PG_URL` set): 7 passed, 73 skipped. Skips = `TEST_POSTGRES_URL` and `TWINGRID_TEST_PG_ASYNC_URL` unset.
- Run 2 (all three set, asyncpg 0.31.0): 75 passed, 2 failed, 3 skipped (80 selected, 5689 deselected).
- Run 3 (after the fix, user-run 2026-10-24): **77 passed, 3 skipped, 0 failed** in 59.34s; `ruff check` and `ruff format --check` clean on the changed file.
- 3 skips are in-test `pytest.skip("PostgreSQL only")` on the SQLite parametrisation (`test_telemetry_ingest.py:414` x2, `:441`).
- 2 failures, both TEST BUGS (`tests/test_audit_migration.py`: `test_pg_user_deletion_still_nulls_actor_but_nothing_else_changes`, `test_pg_rejects_other_updates_even_to_user_id`): raw `INSERT INTO users (id, username, hashed_password, role)` omits `created_at`. `User.created_at` is `Mapped[datetime]` (NOT NULL via `create_all`) with a Python-side `default=utc_now`, which raw SQL bypasses. Product code always inserts through the ORM, so no product defect. Fix: the two INSERTs now supply `created_at` (`now()`). Verified by Run 3.

## Load harness
`tests/test_load_harness.py`: 12 passed in 13.82s with `--timeout=120`. The earlier `locust` import hang did NOT reproduce; nothing changed.

## Frontend skips (vitest 2387 passed, 3 skipped, 2390)
The 3 skipped tests (user-pasted JSON reporter output): `src/contract/driftGate.test.ts`, `fixtures.test.ts`, `openapiSnapshot.test.ts`, each a "NO ... yet" placeholder written as `it.skipIf(<data exists>)`. They skip BECAUSE the data is committed (`src/contract/fixtures/*.json` captured 2026-10-24 against 127.0.0.1:8765, `fixtures/openapi/typed.json`). So no capture is needed; the premise "fixtures still open" was wrong.
Change: each placeholder is now a normal test that FAILS when the fixture set / snapshot is empty or missing (never skips). Expected next vitest run: 2390 passed, 0 skipped. NOT RUN by Claude (no node_modules here); user must run `npx vitest run src/contract`.

## `gate.needs` test
Already exists: `tests/test_ci_gates.py::test_the_gate_job_waits_for_exactly_the_blocking_jobs` (gate.needs == every job without `continue-on-error`, excluding gate/bootstrap). No change.

## Still open
- User: run `npx vitest run src/contract` and paste the summary.
- User: push to GitHub (D4) and paste the Actions run URL; then lower `PYREFLY_ERROR_CEILING` (currently 881) to the measured number and record it in `reports/postT9/T11_ci_run.md`.
