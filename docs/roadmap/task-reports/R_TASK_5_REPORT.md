# R_TASK_5_REPORT: Backend red-test triage

Status: **DONE** (2026-10-24). All 55 originally failing ids pass: the owner's full run is 5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed (`C:\twlogs\pytest_full_final.txt`); every file named in this report shows only passes except one documented environment skip in `test_error_contract` (line 226). Earlier PARTIAL text below is history.
Owner runs used: (0) 2026-10-23 after v4 + `git rm models/scaler.joblib`: 8 failed / 1251 passed / 1 skipped (causes in the second table below); (1) 2026-10-22: 15 files, 55 failed / 486 passed / 1 skipped (+ a locust import hang); (2) 2026-10-23: `tests/api`, `tests/characterization` + 6 files, 22 failed / 1186 passed / 1 skipped; (3) `tests/api/test_error_contract.py` after the route-helper fix: 45 passed, 1 skipped. Python 3.12.10, Windows; torch and TensorFlow 2.21.0 import fine, so no failure is NEEDS-TF. NEEDS-PG tests were deselected (81) and not triaged here.

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

## Run (0): the 8 failures left after v4, and the v5 fixes
| Ids | Class | Cause (evidence) | State |
|---|---|---|---|
| `test_artifact_gate` (3), `test_train_ppo` rollback (1) | REAL BUG | `models/registry.json` is the v2 document `{"registry_version": 2, "artifacts": [...]}`; `scripts/registry_cli.py::load_registry` accepted only a bare list and `write_registry_atomic` wrote one | Fixed in source: the CLI reads both formats and keeps a v2 wrapper (other keys preserved) on write; bare-list files stay lists. Load/write round trip on the shipped registry checked here (equal JSON); NOT RUN under pytest |
| `test_gitignore_source_dirs` (1) | REAL BUG (platform) | unanchored `ENV/` and `ENV*/` in `.gitignore` match `docs/env` when `core.ignorecase=true` (Windows, macOS). Reproduced with real git: old rules ignore `docs/env/Task1.md`, new rules do not | Fixed: `/ENV/`, `/ENV*/` (3 lines); the test now sets `core.ignorecase=true` in its throw-away repo so it fails on every platform for such a rule. Verified with real git, old and new rules; NOT RUN under pytest |
| `test_train_ppo` sha256 (1) | TEST BUG | the registry records the sha256 of the canonical JSON (`canonical(training_params)`), and the five registry values equal that hash; the test hashed the file bytes, and the files on disk end with `\n` (added by a pre-commit end-of-file hook), so bytes differ. Checked here: canonical hash equals the registry for all 5 | Fixed: the test hashes `canonical(json.loads(file))`; it still fails if the config content changes. NOT RUN under pytest |
| `test_baselines` (2) | NEEDS OWNER RUN | unchanged: `reports/runs/baselines-v5` | OPEN |

## Run (4): first whole-suite run (2026-10-24, `-m "not postgres"`, load harness excluded): 6 failed / 5655 passed / 3 skipped / 10 xfailed
The four files from the previous round (242 tests) passed, including both `test_baselines` ids, so those are closed.
| Ids | Class | Cause (evidence) | State |
|---|---|---|---|
| `test_task6_security::test_server_loggers_never_print_a_ticket_or_token`, `test_task7_observability` (5) | REAL BUG (test pollution) | each captured an empty log. `tests/test_bench_suite.py` runs before them and calls `bench_suite.main`, which does `logging.disable(logging.CRITICAL)` and never undoes it, so every later logger in the process is off. Both files passed in the earlier partial runs, which did not include `test_bench_suite` | Fixed in source: `bench_suite.main` and `benchmark_performance.main` restore the previous switch in a `finally`; new regression test `test_main_puts_the_logging_switch_back`. NOT RUN under pytest |
Skips in this run (all 3 documented, none new): `test_error_contract.py:226` (client refuses the header), `test_artifact_integrity.py:205` (symlinks unavailable on Windows), `test_notify_mail.py:153` (Windows localhost reset timing).

## Changed files in this delivery
- MODIFY `tests/test_facility_migration.py`, `tests/test_gitignore_source_dirs.py`, `tests/test_train_ppo.py`
- MODIFY `scripts/registry_cli.py`, `.gitignore`, `scripts/bench_suite.py`, `benchmark_performance.py`, `tests/test_bench_suite.py`
- MODIFY `twin-stream-insight-main/src/features/evidence/generated/claims.json` (regenerated)
- MODIFY `docs/roadmap/failure-ledger.csv` (every Task 5 row now has a state and cause)
- MODIFY `docs/roadmap/task-reports/R_TASK_5_REPORT.md`
- DELETE (command, not in the zip) `models/scaler.joblib`
Earlier, already committed: `reports/postT9/T14_route_controls.py`.

## Commands run / Not run
Run here: `ruff check` and `ruff format --check` on the changed Python files (ruff 0.16.9, not the pinned 0.6.9); the `.gitignore` logic against real git; `scripts/build_evidence.py` and `--check`. Owner runs as listed above.
NOT RUN: `tests/test_facility_migration.py`, `tests/test_gitignore_source_dirs.py`, `tests/test_artifact_gate.py`, `tests/test_train_ppo.py` under pytest (no pytest in this sandbox); the newer-tree test rewrites; `tests/test_load_harness.py`; the baselines-v5 run; the full suite; the Postgres set.

## Acceptance checklist
- Every failing id has a ledger row and a cause: MET (40 rows; each Task 5 row has state and cause).
- Zero unexplained failures: NOT MET until the owner run below passes; the 2 baselines tests stay OPEN until the ML-002 run is committed.
- Env-only failures marked with a documented marker: none needed; the `.gitignore` case was fixed in the rules (and made hermetic), not skipped.

## Decisions used
The newer tree's rewrites of the registry tests were kept (not reverted). The `.gitignore` test checks the repo's rules only. Nothing was skipped or loosened.

## Requested cross-task changes
Task 8: `tests/test_baselines.py` still depends on a run that is not committed (ML-002).

## L4 update (2026-10-24): run evidence
Files that carried this task's ids and show only passes in `C:\twlogs\pytest_full_final.txt`: `test_pue_hard_constraint`, `test_recommendation_ranges`, `test_repro_framework`, `test_t23_carbon_aqueduct_contracts`, `test_task19_optimizer_rules`, `test_task9_api_reference`, `test_artifact_gate`, `test_baselines`, `test_build_evidence`, `test_datasets_v2`, `test_facility_migration`, `test_gitignore_source_dirs`, `test_load_harness`, `test_train_ppo`, `test_task6_security`, `test_task7_observability`, `api/test_error_contract` (1 skip), `api/test_provenance_writers`, `api/test_physics_v1_api`, `api/test_routes_health_metrics`, `api/test_state_preview_isolation`, `api/test_task29_admin_console`, and the four `characterization` files. The `models/scaler.joblib` test passes, so the `git rm` it needed is in effect. The "NOT RUN under pytest" lines in the Commands section are superseded by this run. Per-test ids were not in the pasted output (dots only), so the proof is per file.
