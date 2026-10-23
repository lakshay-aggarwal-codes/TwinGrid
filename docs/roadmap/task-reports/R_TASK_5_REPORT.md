# R_TASK_5_REPORT: Backend red-test triage

Status: PARTIAL. 33 of the 55 originally failing ids are verified fixed by owner runs; 18 more are fixed in code and need one owner run; 1 needs `git rm`; 2 need an owner run of the baselines tooling (ML-002).
Owner runs used: (1) 2026-10-22: 15 files, 55 failed / 486 passed / 1 skipped (+ a locust import hang); (2) 2026-10-23: `tests/api`, `tests/characterization` + 6 files, 22 failed / 1186 passed / 1 skipped; (3) `tests/api/test_error_contract.py` after the route-helper fix: 45 passed, 1 skipped. Python 3.12.10, Windows; torch and TensorFlow 2.21.0 import fine, so no failure is NEEDS-TF. NEEDS-PG tests were deselected (81) and not triaged here.

## What the 22 remaining failures of run (2) were, and what happened to each
| Ids | Class | Cause (evidence) | State |
|---|---|---|---|
| `test_physics_v1_api` shapes (1) | TEST BUG | `/api/whatif` returns `{**result, "scenario_id": ...}`; the legacy golden key set lacks the additive key (read from `digital_twin_routes.py` and the golden JSON) | Fixed in the newer tree (test expects `scenario_id`); NOT RUN |
| `test_state_preview_isolation` (1) | TEST BUG | each tick carries `seq` (module counter), window contents and a wall-clock `scored_at`, so two ticks never compare equal (`live_broadcast_service.py`) | Fixed in the newer tree; NOT RUN |
| `test_artifact_gate` registry_cli (11) | TEST/SOURCE DRIFT | tests drove an older CLI (`--audit`, `_audit_backend`, exit 3); `scripts/registry_cli.py` is the T30 CLI | Tests rewritten to the current CLI in the newer tree; NOT RUN |
| `test_artifact_gate` scalers (1) | REAL (stray file) | `models/scaler.joblib` is a third, top-level copy, byte-identical to `models/_legacy/scaler.joblib` (sha256 checked), read by nothing | `git rm models/scaler.joblib` (command below) |
| `test_baselines` (2) | NEEDS OWNER RUN | `reports/runs/baselines-v5` is produced by the owner's machine run (`docs/roadmap/ML-002_RUNBOOK.md`) and is not in the repo | OPEN |
| `test_build_evidence` (1) | REAL (stale generated file) | `docs/CLAIMS.md` C-06 was reworded after `claims.json` was generated; `build_evidence.py --check` exited 1 | REGENERATED here (`--check` exits 0); only `claims.json` changed |
| `test_facility_migration` (4) | TEST BUG | database stamped at `20250223000000`, but M3's `down_revision` is `20261001000001` (M2 -> M1 -> 20250223000000), so `upgrade M3` also ran M1 and M2 on stand-in tables | Fixed: `PREV` read from M3's own `down_revision`; NOT RUN |
| `test_gitignore_source_dirs` (1) | ENV | the repo's `.gitignore` files do not ignore `docs/env/Task1.md` (checked with git); the owner's machine matched a rule outside the repo | Fixed: test now uses a throw-away repo with copies of the repo's `.gitignore` files and no global/XDG/`info/exclude` rules; verified here with real git (both assertions hold) |
Earlier (run 1) groups already verified fixed in run 2: `test_error_contract` 14 (route-helper fix: `_walk` carries `include_context.dependencies`), `test_provenance_writers` 5, `test_routes_health_metrics`, `test_task15`/`test_task27` retry-after (2), `test_task29_admin_console`, `characterization/*` (9), `test_datasets_v2`.
Flaky: `test_compute_exception_releases_the_slot` failed once and passed on re-run (order-dependent; no change). `test_load_harness`: `importorskip("locust")` deadlocked in an import lock (gevent) on Windows; the newer tree no longer imports `locustfile.py` in that test; NOT RUN.

## Changed files in this delivery
- MODIFY `tests/test_facility_migration.py`, `tests/test_gitignore_source_dirs.py`
- MODIFY `twin-stream-insight-main/src/features/evidence/generated/claims.json` (regenerated)
- MODIFY `docs/roadmap/failure-ledger.csv` (every Task 5 row now has a state and cause)
- MODIFY `docs/roadmap/task-reports/R_TASK_5_REPORT.md`
- DELETE (command, not in the zip) `models/scaler.joblib`
Earlier, already committed: `reports/postT9/T14_route_controls.py`.

## Commands run / Not run
Run here: `py_compile`, `ruff check` and `ruff format --check` on the two test files (ruff 0.16.9, not the pinned 0.6.9); the `.gitignore` logic against real git; `scripts/build_evidence.py` and `--check`. Owner runs as listed above.
NOT RUN: `tests/test_facility_migration.py`, `tests/test_gitignore_source_dirs.py` under pytest; the newer-tree test rewrites; `tests/test_load_harness.py`; the baselines-v5 run; the full suite; the Postgres set.

## Acceptance checklist
- Every failing id has a ledger row and a cause: MET (40 rows; each Task 5 row has state and cause).
- Zero unexplained failures: NOT MET until the owner run below passes; the 2 baselines tests stay OPEN until the ML-002 run is committed.
- Env-only failures marked with a documented marker: none needed; the one environment case (`.gitignore`) was made hermetic instead of skipped.

## Decisions used
The newer tree's rewrites of the registry tests were kept (not reverted). The `.gitignore` test checks the repo's rules only. Nothing was skipped or loosened.

## Requested cross-task changes
Task 8: `tests/test_baselines.py` still depends on a run that is not committed (ML-002).
