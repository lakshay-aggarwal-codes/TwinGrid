# R_TASK_5_REPORT: Backend red-test triage

Status: PARTIAL. Update 2026-10-23: owner confirmed `include_context.dependencies` is a list of `Depends` (printed from the real app); the helper now carries those down. First pass from the owner's 2026-10-22/23 run (55 failed, 486 passed, 1 skipped on the 15 failing files; torch and TensorFlow 2.21.0 import fine in the venv).
One fix delivered. The rest is classified from the log only and NOT fixed, because the uploaded zip is not the owner's current tree (see "Tree mismatch").

## Tree mismatch (blocks further fixes)
Evidence that the zip used for this task differs from the owner's repo (HEAD 2c4639c, branch wip/bc10-run-contract):
- Owner's `test_provenance_writers.py` has `test_state_reading_is_stamped` and expects `legacy-0`; the zip's file has `test_state_is_a_stateless_preview_and_no_longer_a_writer` and uses `active_physics_version()`.
- Owner's `git check-ignore` ignores `docs/env/Task1.md`; the zip's `.gitignore` anchors the rule (`/env*/`) and does not.
- Owner's tests read `reports/runs/baselines-v5/manifest.json`; the zip has baselines-v2..v4 only.
Line numbers in `test_error_contract.py` do match (367, 392, 399), so that file is identical.

## Classification (55 failures + 1 hang)
| Group | n | Class | Basis |
|---|---|---|---|
| `api/test_error_contract` (route table, heavy-route scopes, operator routes) | 14 | TEST BUG (harness) | PROVEN by reading: `reports/postT9/T14_route_controls.py::_walk` only descends `.routes`; FastAPI 0.141.1 keeps included routers opaque, so the table is empty ("no routes found"; StopIteration; KeyError). FIXED in two steps (walker; then include-level dependencies, because `main.py` and `load_plugins` attach the general limit via `include_router(dependencies=...)`, which FastAPI 0.141.1 keeps in `include_context.dependencies`, not on the route). Step 1 took the group from 14 failures to 2 (owner run). Step 2 not yet run. |
| `characterization/test_route_contracts_and_targets` | 4 | TEST BUG (obsolete) | Log: `[XPASS(strict)] T2` and `T0b`: the "target" tests now pass, so the task is done; the two `legacy_behavior` tests assert the old behaviour. Remove the xfail markers and delete/rewrite the legacy tests. Needs the owner's file. |
| `characterization/test_ws_payload_provenance` | 1 | TEST BUG (obsolete) | Legacy test asserts provenance fields are NOT persisted; they now are. Needs the owner's file. |
| `characterization/test_ws_and_manager_contract` (3), `test_t3_anomaly_pipeline` (1) | 4 | UNDETERMINED | `broadcast()` returns `[]` / pipeline-once assertion. Need the owner's source + test. |
| `api/test_provenance_writers` | 5 | TEST BUG (stale vs code) | Code returns physics `1`; tests expect `legacy-0`. The zip's version of this file already uses `active_physics_version()`. |
| `test_gitignore_source_dirs` | 1 | REAL BUG (owner's `.gitignore`) | `docs/env/Task1.md` is ignored in the owner's repo; the zip's anchored rule fixes it. |
| `test_baselines` | 2 | REAL (missing committed data) | `reports/runs/baselines-v5/manifest.json` not found. Either not committed or ignored (see previous row). |
| `test_artifact_gate` | 12 | UNDETERMINED | `scripts/registry_cli.py` lacks `_audit_backend` / `AUDIT_TIMEOUT_S` (11); one scaler-equality assertion. Source vs test drift. Needs the owner's files. |
| `test_facility_migration` | 4 | UNDETERMINED | alembic upgrade/downgrade assertions fail (output starts at `Context impl SQLiteImpl`); likely a migration-chain change. Need the full assertion text. |
| `test_routes_health_metrics`, `test_state_preview_isolation`, `test_task15_whatif_sensitivity`, `test_task27_carbon_schedule_route`, `test_task29_admin_console`, `test_physics_v1_api`, `test_build_evidence`, `test_datasets_v2` | 8 | UNDETERMINED | One failure each; messages in the log are truncated. |
| `test_load_harness` | 1+hang | FLAKY / ENV | `importorskip("locust")` blocked on an import lock for 180 s (gevent import on Windows). Needs a documented marker or a subprocess import; not changed yet. |
No failure is NEEDS-TF (TensorFlow and torch import in the venv). NEEDS-PG tests were deselected (81) by `-m "not postgres"`.

## Changed files
- MODIFY `reports/postT9/T14_route_controls.py` (`_walk` descends included routers and carries their dependencies; `_all_calls`/`_limit`/`_auth` take them)
- CREATE `docs/roadmap/task-reports/R_TASK_5_REPORT.md`
`docs/roadmap/failure-ledger.csv` NOT updated yet: rows would be guesses until the tree matches.

## Commands run / Not run
`py_compile` and `ruff check` on the helper. Owner run after step 1: `test_error_contract.py` 2 failed, 43 passed, 1 skipped. Still failing then: `test_every_http_route_has_an_http_limit_except_the_probes` (35 routes shown as NONE; cause above, fixed in step 2, not yet run) and `test_compute_exception_releases_the_slot` (not in the first 55; traceback not yet seen; run alone printed nothing). NOT RUN: step 2.

## Acceptance checklist
Every failing id has a ledger row and cause: NOT MET (classified above; ledger pending). Zero unexplained failures: NOT MET.

## Requested cross-task changes
None.
