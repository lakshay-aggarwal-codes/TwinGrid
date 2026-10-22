# R_TASK_5_REPORT: Backend red-test triage

Status: PARTIAL. 55 failures in 15 files classified; 28 ids fixed (not yet re-run); 4 groups need one diagnostic each;
2 need an owner action; 1 needs an owner decision.

## Basis
Owner run 2026-10-22, Windows, Python 3.12.10 venv (torch and TensorFlow 2.21.0 import fine, so none of these are NEEDS-TF):
`pytest` on 15 files: 55 failed, 486 passed, 1 skipped. The full 5,769-test run was not completed (it stopped at 41%), and
`tests/test_load_harness.py` hung 180 s on `importorskip("locust")`. Postgres set not run. Failures not covered by those 15 files are NOT classified.
Everything below was read from the 2026-10-21 tree; nothing could be run in the cloud workspace.

## Classification (full detail in docs/roadmap/failure-ledger.csv)
| Group | ids | Class | State |
|---|---|---|---|
| error_contract route table | 14 | TEST-HELPER BUG (T14 helper cannot see lazily-included routers) | OPEN, needs `include_context` attributes |
| provenance_writers | 5 | TEST BUG (physics default, /api/state no longer writes, summary carries model/physics) | fixed |
| physics_v1_api shape | 1 | unresolved | OPEN, needs set difference |
| healthz 503 body | 1 | TEST BUG (problem+json body) | fixed |
| state preview isolation | 1 | TEST BUG (clock is `utc_now`) | fixed |
| Retry-After on slowapi 429 | 2 | REAL BUG (`api/errors.py`) | fixed |
| admin console duplicate webhook | 1 | TEST BUG (ORM identity compare) | fixed |
| characterization route contracts | 4 | TEST BUG (legacy tests deleted, 2 XPASS targets promoted) | fixed |
| t3 anomaly pipeline | 1 | TEST BUG (broadcast is async) | fixed |
| ws manager contract | 3 | TEST BUG (broadcast is async; legacy stall test replaced) | fixed |
| ws payload provenance | 1 | TEST BUG (`origin` persisted by design) | fixed |
| shipped scaler pickles | 1 | REAL BUG (duplicate `scaler.joblib`) | DELETE 2 files (command) |
| registry CLI (artifact_gate) | 11 | REAL BUG / owner decision | OPEN |
| baselines-v5 | 2 | NEEDS-OWNER-RUN | OPEN, runbook command |
| build evidence | 1 | REAL BUG (stale generated files) | OPEN, regenerate |
| datasets_v2 | 1 | REAL BUG (default path frozen at import) | fixed |
| facility_migration | 4 | unresolved | OPEN, needs alembic stderr |
| gitignore | 1 | ENV suspected (global ignore) | OPEN, needs `check-ignore -v` |
| load_harness | 1 + hang | FLAKY / ENV (locust import deadlock) | OPEN |

## Acceptance checklist
- Every failing id has a ledger row and a cause: MET for the 55 ids from the owner run (rows are per group, ids named in the row).
- Zero unexplained failures: NOT MET: physics_v1_api (1), facility_migration (4), gitignore (1) and load_harness have a hypothesis, not a proof.
- REAL and TEST bugs fixed: PARTIAL (see table). Nothing was marked with a blanket skip or a new xfail; two xfail markers were REMOVED because the targets pass.

## Changed files
MODIFY api/errors.py; src/data_generator.py; tests/api/test_provenance_writers.py; tests/api/test_routes_health_metrics.py;
tests/api/test_state_preview_isolation.py; tests/api/test_task29_admin_console.py; tests/characterization/test_route_contracts_and_targets.py;
tests/characterization/test_ws_and_manager_contract.py; tests/characterization/test_t3_anomaly_pipeline.py; tests/characterization/test_ws_payload_provenance.py;
docs/roadmap/failure-ledger.csv. CREATE tests/api/test_rate_limit_retry_after.py; docs/roadmap/task-reports/R_TASK_5_REPORT.md.
DELETE (owner command) models/anomaly/scaler.joblib; models/forecaster/scaler.joblib.

## Commands run
`py_compile` and `ruff check` / `ruff format --check` (ruff 0.16.9; the project pins 0.6.9, so re-run with yours) on every changed Python file. No pytest (no package access).

## Not run
`pytest` on every changed file (command in the reply). The rest of the 5,769-test suite and the Postgres set.

## Decisions used
Per the characterization marker contract, a landed task deletes its `legacy_behavior` test and removes the xfail from a target that now passes.
Retry-After on slowapi 429s is the window length (an upper bound), sent only when the exception carries a limit.

## Requested cross-task changes
- Task 8: the registry-CLI decision decides whether those 11 tests stay; `test_load_harness` locust import needs a documented environment marker if the deadlock is confirmed.
- Task 7: regenerating the evidence files and the baselines-v5 run feed the evidence page.
