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
Change: each placeholder is now a normal test that FAILS when the fixture set / snapshot is empty or missing (never skips). Verified by the owner 2026-10-24: vitest 184 files, 2390 passed, 0 skipped; `pytest tests/test_ci_gates.py` 6 passed.

## `gate.needs` test
Already exists: `tests/test_ci_gates.py::test_the_gate_job_waits_for_exactly_the_blocking_jobs` (gate.needs == every job without `continue-on-error`, excluding gate/bootstrap). No change.

## Still open
- User: push to GitHub (D4) and paste the Actions run URL; then lower `PYREFLY_ERROR_CEILING` (currently 881) to the measured number and record it in `reports/postT9/T11_ci_run.md`.


## CI on the pull request (R3 Task 11, owner's run 2026-10-25)
PR #86, `wip/bc10-run-contract` -> `main`, first run. 7 passed, 11 failed, 1 skipped (`bootstrap`, manual only).

| Job | Result | Cause (from the pasted log) |
|---|---|---|
| lint, test-postgres (2m41s), docker, CodeQL, gitleaks | passed | The Postgres suite passes in CI. |
| test | failed: 8 failed, 5730 passed, 1 skipped, 81 deselected | 5 x `No module named 'jsonschema'` (test_load_harness; fixed: added to `requirements-dev.txt`). 3 more: `assert 'ok' == 'degraded'`, a `code_revision` mismatch (recorded `c2dd59f`, now `551f4cc`), and `MissingInputError` for `data/cleaned/weather_open_meteo.csv`. Test ids not yet seen. |
| frontend-contract, frontend-e2e | failed in 10-16 s | `docker compose up` stops: `MQTT_BROKER` is required by the opt-in `mqtt-ingest` service and compose interpolates every service. Fixed in `ci.yml` (dummy value on the two steps). |
| types, audit, frontend, gate | failed | `gate` fails because types, test, audit and frontend did. Logs for types, audit and frontend not yet seen. |
| Netlify (4 checks) | failed | Not part of CI; log not yet seen. |

Status: **PARTIAL**. The Postgres evidence this report wanted is now in CI; the branch is not green.
Note: `PYREFLY_ERROR_CEILING` is 1120 in `ci.yml`, not 881.

### Second CI round (PR #86)

- `frontend`: `WhatIfResponse.provenance` typed with all-optional fields (zod output makes them optional).
- `audit`: two recorded waivers (see `reports/postT9/T11_ci_run.md`).
- `test`: fanout test waits for the 1013 close code; anomaly-throttle reset; synthetic-data flags; `fetch-depth: 0` for the ancestor check.
- `frontend-contract`: drift against committed fixtures. Fix is to commit the CI-captured fixtures (artifact `contract-fixtures`), not a code change.
- `frontend-e2e`: advisory; 15 failures, mostly missing `E2E_ADMIN_*` env vars in the job. Not fixed in this round.
- Netlify checks: not diagnosed (log not seen).

### Third CI round (PR #86, head 440098c, recorded 2026-10-27)
10 failing, 8 successful, 1 skipped (`bootstrap`, manual only), 0 pending. Status: **PARTIAL**, not green.
| Result | Checks |
|---|---|
| failed | CI/frontend, CI/frontend-e2e (12m49s), CI/test (13m42s), CI/types (1m13s), Secret scan/gitleaks (7s), CI/gate (follows its needed jobs), Netlify: Header rules, Pages changed, Redirect rules, deploy-preview |
| passed | CI/frontend-contract, CI/lint, CI/audit, CI/docker, CI/test-postgres, CodeQL (javascript-typescript, python) |
Causes are recorded only where a log was read; none are recorded for these failures yet.

### Final CI state (PR #87, commit cee2af9, 2026-10-27)

Green on the pull request: lint, types (ceiling 1125 errors), test, test-postgres, audit (two recorded pip-audit waivers), frontend (npm audit gate with one recorded zod waiver), frontend-contract (fixtures re-captured), docker, gitleaks, CodeQL (python, javascript-typescript), gate.

Not green:
- frontend-e2e: advisory (`continue-on-error`), so the `continue-on-error` line stays. In the earlier run, 15 tests failed, 12 were skipped and 52 passed; the admin-console accessibility tests fail because E2E_ADMIN_USERNAME and E2E_ADMIN_PASSWORD are not set in the job. The remaining failures (E2E-22 file/demo/smtp) have not been diagnosed.
- Netlify (header rules, pages changed, redirect rules, deploy preview): failing, cause not yet read from the Netlify deploy log. Not part of the CI gate.

History: PR #86 was merged to main while its checks were red; PR #87 carries the fixes. main's own CI runs for #83 and #86 were also red.

Verdict for L6: the Postgres suite and contract fixtures are recorded green in CI; the Docker e2e stack is NOT recorded green, so L6 stays PARTIAL on that point.

## Final CI state (2026-10-27)
- Linux run https://github.com/lakshay-aggarwal-codes/TwinGrid/actions/runs/40456418959 (commit cda7c2f): `test` 5739 passed, 0 failed; `test-postgres`, `types` (944 errors), `frontend` (185 files, 2401 tests), `frontend-contract`, `audit`, `lint`, `docker` all green.
- Linux run https://github.com/lakshay-aggarwal-codes/TwinGrid/actions/runs/40499776651 (commit 459c919): `gate` success; `frontend-e2e` failure (advisory, not part of the gate).
- Pyrefly ceiling lowered 1125 -> 944 (recorded in reports/postT9/T11_ci_run.md).
- Fixes needed to get here: runner pinned to ubuntu-24.04 (ubuntu-latest is 26.04 and has no Python 3.12.10); lock regenerated on Linux with pip-compile; PyYAML added to requirements-dev.txt; auth tests isolated from VITE_DEMO_*; the `types` job installs requirements-dev.txt; three tests made deterministic; `WhatIfResponse.provenance` fields made optional.
- Verdict: **DONE** for the blocking gate. Open: `frontend-e2e` (advisory).
