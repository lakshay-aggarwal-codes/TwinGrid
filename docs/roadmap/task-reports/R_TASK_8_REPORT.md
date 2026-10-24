# R_TASK_8_REPORT: No skipped tests

Status: **PARTIAL** (2026-10-24). Backend is done: the owner's `pytest -rsx` run shows 3 skips, each with a printed environment reason, and 0 unexplained. Still not shown: the vitest skipped list (frontend).

## Basis
Read of the uploaded tree (`TwinGrid-main.zip`, 2026-10-21), by grep. It predates your Task 1-3 commits, so the copilot xfails below may already be gone in your repo.
Every skip in the tree already carries a reason string; the problem is skips that HIDE a real failure, and xfails with no task pointer.

## Changes made (3, each removes a skip that could mask a real import error)
- `tests/test_anomaly_eval.py`: `src/data_pipeline.py` exists in the tree; the `ImportError -> skip("not in this tree")` is now a plain import.
- `tests/test_task26_capacity.py`: `importorskip("api.plugins.capacity")` -> plain import (FastAPI is locked in `requirements.lock`).
- `tests/test_task27_carbon_schedule.py`: `importorskip("fastapi")` -> plain import (same reason).
Risk: if one of these now FAILS on your machine, that is a real import problem that the skip was hiding. Send me the output.

## Inventory: Python (backend)
| Category | Where | Verdict |
|---|---|---|
| Optional heavy dependency (`importorskip`) | torch+stable_baselines3 (`test_train_ppo`, `test_numpy_policy`), gymnasium (`test_sensitivity`, `test_artifact_gate`, `test_robustness_eval` x3), joblib x2, prometheus_client, scipy.stats, pandas x2 (`test_forecast_eval`), reportlab, locust, websockets, alembic+aiosqlite (`test_alembic_chain`, `test_task28_migration`) | Environment marker. KEEP, with reason. Needs your `-rs` output to know which fire. pandas, alembic, aiosqlite are in dev/runtime pins: check they do not fire (they would be hiding failures). |
| Own module via `importorskip` | `test_artifact_integrity` (`api.services.anomaly_service`, `src.task_queue` x3) | UNDECIDED. May legitimately need TensorFlow/redis; convert to plain imports only if `-rs` shows they skip where TF/rq are installed. |
| PostgreSQL needed | `test_time_contract`, `test_audit_migration`, `test_telemetry_ingest` x3, `test_provenance_m1` | Environment marker (NEEDS-PG). KEEP; run via the Postgres job (Task 5/7). |
| Physics-version dependent | `test_recommendation_ranges` x7, `api/test_task3_recommendation_ranges` | Conditional on `active_physics_version()`. KEEP; confirm in `-rs` they run under physics 1 (the default). |
| External tool absent | node (`test_ig05_rack_id_parity` x2, `test_facility_seed` x2), git (`test_repro_framework`, `test_gitignore_source_dirs` x2), symlinks (`test_artifact_integrity`) | Environment marker. KEEP. |
| Data not committed | `test_task20_docs_consistency` x2 (Task 9 `results.json`, "only meaningful for outcome C"), `test_audit_regressions` (real carbon curve installed), `api/test_error_contract` (client refuses header) | KEEP if reason is accurate; `test_task20_docs_consistency` skip for a missing results file is a gap: commit the file or make the test fail. Needs a decision. |
| xfail (strict) | `test_copilot_adversarial` x4 (Tasks 1, 2, 3 of this roadmap), `characterization/test_route_contracts_and_targets` `@target("T2")` x1 | The 4 copilot ones belong to Tasks 1-3 and must be gone after them. `T2` is the old numbering: reason should name a current task. |
| xfail (strict), no task | `test_audit_regressions::test_optimized_twin_matches_the_main_twin_on_the_benchmark_inputs` (TG-A-05: optimized twin differs from legacy twin by ~20 C outlet) | Real open defect with no owner. Decision: fix, retire `digital_twin_optimized`, or point at a task number. |

## Inventory: frontend
- Vitest "10 skipped" (not listed in your output). By grep, the candidates are `src/contract/driftGate.test.ts`, `openapiSnapshot.test.ts`, `fixtures.test.ts` (`skipIf` on committed fixtures / OpenAPI snapshot). They clear when Task 7 commits real fixtures and the snapshot. List them: `npx vitest run --reporter=verbose | Select-String "skipped|↓"`.
- Playwright (`e2e/`), conditional on environment, each with a reason: `perf.spec.ts` x3 (opt-in `PERF=1`, S4 data size, missing `dist/`), `drills.spec.ts` (needs `E2E_DRILL_DEMO_SHORT=1`), `a11y.spec.ts` (depends on an earlier test), `viewer-workflow.spec.ts` (`E2E_DEMO_DISABLED=1`). KEEP as environment markers; they are not part of the default unit run.

## Acceptance checklist
- Every skip and xfail listed with reason: MET for the uploaded tree (above).
- Fix / delete / convert each: PARTIAL (3 fixed; rest classified, awaiting `-rs`).
- `pytest -rs` shows 0 unexplained skips: NOT VERIFIED (not run).

## Changed files
- MODIFY `tests/test_anomaly_eval.py`, `tests/test_task26_capacity.py`, `tests/test_task27_carbon_schedule.py`
- CREATE `docs/roadmap/task-reports/R_TASK_8_REPORT.md`

## Commands run
`python3 -m py_compile` on the three edited files (ok). Nothing else; the cloud workspace cannot install packages.

## Not run
`pytest tests/test_anomaly_eval.py tests/test_task26_capacity.py tests/test_task27_carbon_schedule.py -q`, then the full `pytest tests -m "not postgres" -rs -q`.

## Decisions used
Skips that mask failures of locked runtime dependencies are removed; environment skips keep their reason strings.

## Requested cross-task changes
- Tasks 1-3: remove the four `test_copilot_adversarial` xfails (in your repo they may already be removed).
- Task 7: commit fixtures and OpenAPI snapshot so the frontend contract skips clear.

## L4 update (2026-10-24): backend skip count
`pytest tests -m "not postgres" -rsx -q` (`C:\twlogs\pytest_full_final.txt`): 5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed. The 3 skips: `tests\api\test_error_contract.py:226` (client refuses to send that header), `tests\test_artifact_integrity.py:205` (symlinks not available), `tests\test_notify_mail.py:153` (Windows does not reset a closed localhost port at once). All three are environment limits with a stated reason. The 9 xfails are strict and share one reason (the open validator defect, L1). The 81 deselected tests are `-m postgres` and are covered by L6, not by this count. Frontend: no vitest output was pasted, so the frontend half of "0 unexplained skips" stays NOT VERIFIED.
