# Task 21 — QA-002 CI hardening, first green run, API reference          Status: PARTIAL
Base: uploaded TwinGrid-main.zip (Tasks 1-18 reports present; owner's working copy and `git status` not seen)   Date: 2026-10-21
Environment: Python 3.12.3, Node 22.22.2, PyYAML. No network: no ruff, pytest, fastapi, torch, Postgres, Docker, npm packages. **No CI job was run.**

## Summary
Static audit of `ci.yml` against the tests it runs. Found four causes that make the "no skipped tests" gates fail, fixed them, added job summaries
(runtime versions, counts) and owner/expiry notes on the two advisory jobs. `docs/api/`, contract fixtures and the pyrefly count need your machine.

## Acceptance checklist
| Criterion | Status | Evidence |
|---|---|---|
| Required jobs pass locally | NOT VERIFIED | nothing runnable here; commands below |
| Advisory flags justified | MET | owner + expiry comments on `frontend-e2e`, `frontend-contract`; no green run recorded, so still advisory |
| `docs/api/` present and in sync | NOT MET | needs fastapi; `docs/api/` is absent, so `tests/test_task9_api_reference.py` fails today; step added to CI too |
| Real contract fixtures committed | NOT MET | needs the compose backend; `twin-stream-insight-main/src/contract/fixtures/` holds a README only |
| Ceiling lowered to measured count | NOT MET | not measured; stays 881 |
| CI summaries print versions and counts | MET (YAML parses, 4 inline Python blocks compile; never executed on a runner) | |

## Changed files
- `.github/workflows/ci.yml`: node pin + locust install + `gen_api_reference.py --check` in `test`; `TEST_POSTGRES_URL`, `TWINGRID_TEST_PG_ASYNC_URL` and `-k "not sqlite"` in `test-postgres`; job summaries; advisory owner/expiry.
- `tests/conftest.py`: tests whose skipif names a PG URL variable get the `postgres` marker (was: name contains "postgres" only).
- `tests/test_pue_hard_constraint.py`: stale-rule test builds its own stale config in `tmp_path` instead of skipping once configs are re-tuned.
- `reports/postT9/T11_ci_run.md`: Task 21 record.

## Findings (read from the code, hypotheses until the jobs run)
1. `tests/test_audit_migration.py::test_pg_*` and the pg variants in `tests/test_telemetry_ingest.py` carry a skipif but no `postgres` name, so `-m "not postgres"` kept them and they skipped.
2. `test-postgres` never set their URL variables (asyncpg URLs needed).
3. `tests/test_load_harness.py` importorskips `locust`; it is in neither requirements file (only `load.yml`).
4. Stale-rule test in `test_pue_hard_constraint.py` skips when `configs/baselines/rule.json` already carries the current rule, which is the case in this tree.
5. Checked and fine: physics default is "1" (recommendation-range skipifs do not fire in CI); alembic, aiosqlite, reportlab, scipy, joblib, gymnasium, prometheus_client are installed by lock or dev file.

## Not run / blocked
Every job. Owner commands are in the reply.

## Decisions and defaults used
Advisory expiry 2026-11-30 (my default). `locust>=2.20,<3` is an unverified range.

## Requested cross-task changes
Add `locust` to `requirements-dev.txt`, then delete the temporary install step. Commit `reports/policy_evaluation_physics1/full_0fcafef9d28fd539` if `tests/test_task20_docs_consistency.py` skips for you.

## New limitations or risks
`-k "not sqlite"` in `test-postgres` deselects by substring; a postgres test with "sqlite" in its id would be dropped silently.
Other possible skips not checked: `test_error_contract.py:226`, `test_artifact_integrity.py:205`.

## Next tasks unblocked
None until the required jobs are shown green. Task 29 needs this.
