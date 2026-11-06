# Task 1 — Current repository identity and baseline

**Status: Ready for review** (with open items listed below; owner decides acceptance)

## Base commit and branch
- Repo root: `C:/Users/Lakshay/Desktop/data center/DigitalTwin-main`
- Branch: `wip/cp8-hardening`
- HEAD: `d40daafa60ac589a0a048b4c99be8ff5115138cb` (2026-11-03 15:57:31 +0530, "CP-11: copilot ops docs, runbooks, claims C-36..C-39, model card, perf specs, DocsRetriever min_coverage")
- Parent: `b72f0f3` (2026-11-03 15:45:32, "Add Danish AAU Phase 2 evaluation harness"). The handoff's expected commit is therefore **not HEAD**; HEAD is the baseline of record (handoff section 2 rule).
- `git status --short`: untracked only: `.cp9_backup/`, `cp8_patch.py`, `cp9_apply_product_patch.py`, `selftest.json`, `task1_out/`. No modified tracked files.
- Ignored and present: `realData/`, `research/danish_aau/reports/`.
- Tracked files under `research/danish_aau`: 55 (matches handoff).
- Raw data path `realData/danish-server-room-v5/raw`: **present**. Contains 22 entries (21 files in manifest per its `total_files`; directory listing also shows folders `_3d`, `_mv`, plus layout/dwg/log/xlsx/zip files). Inventory and checksums belong to Task 2, not done here.

## Environment (owner machine, Windows, .venv)
Python 3.12.10; pip 26.2.1; Node v24.18.0; npm 11.16.0; ruff 0.6.9; pytest 8.4.2 (asyncio 1.4.0, cov 7.1.0, timeout 2.4.0, anyio 4.15.1).
numpy 2.5.3, pandas 3.0.6, scipy 1.18.1, SQLAlchemy 2.0.54, alembic 1.20.0, fastapi 0.141.1, tensorflow 2.21.0, torch 2.14.0.
Frontend pins (package.json): react ^18.3.1, typescript ^5.8.3, vite ^7.3.7, vitest ^5.0.4 (vitest ran as v5.0.4).
**Mismatch:** frontend `engines` requires node `>=22.20.0 <23` (`.nvmrc` 22.20.0); the run used Node v24.18.0. Frontend results are from an unsupported Node version.

## Executed results
| Check | Result |
|---|---|
| Danish AAU (`research/danish_aau/tests`) | **446 passed**, 59.27 s. Historical count reproduced. |
| Backend (`tests`) | **4 failed, 6363 passed, 78 skipped, 2 deselected**, 20m36s (6447 collected) |
| Ruff check | 1 error: F401 unused `re` in untracked `cp8_patch.py`. No error in tracked code. |
| Ruff format --check | 546 files already formatted |
| tsc app / tsc node | both exit 0 |
| ESLint `--max-warnings 0` | exit 0 |
| Vitest | **1 file failed, 186 passed (187 files); 5 failed, 2443 passed (2448 tests)** |
| PostgreSQL-dependent tests | **Not run** (env vars unset). Skipped, not passed: `test_audit_migration` (3, TEST_POSTGRES_URL), `test_provenance_m1` (1, TWINGRID_TEST_PG_URL), `test_time_contract` (1), `test_telemetry_ingest` (many, TWINGRID_TEST_PG_ASYNC_URL). |
| Windows regression file (handoff: 119 passed) | **Not identified, not run.** Only `tests/test_notify_mail.py` references `sys.platform`; owner must name the file. |

### Backend failures (not fixed, per Task 1 rules)
1. `tests/test_build_evidence.py::test_committed_generated_files_match_the_repository`: "stale or missing: claims.json".
2. `tests/test_copilot_rag_search.py::...[what are the Copilot limits-LIMITS.md]`: best_score 4.813 below min_score 6.5.
3. `tests/test_external_register.py::test_real_register_passes_every_rule` and 4. `::test_checker_cli_exits_zero_on_the_real_repository`: `data/external/REGISTER.json` has no entry for `realData/danish-server-room-v5`, referenced by `audit_danish_aau.py`, `config/default.toml`, `evaluation/paths.py`.
Whether failures 1-2 pre-date HEAD or relate to the untracked files was not tested. Failures 3-4 show the Danish AAU dataset lacks a register entry; relevant to Tasks 2 and 10.

### Frontend failure
`src/components/DashboardSidebar.readonly.test.tsx`: all 5 tests failed (viewer lock, current values, operator, admin, collapse toggle). Failure messages were not captured in the output supplied; cause unknown (Node 24 vs required 22 is one unverified candidate).

## Files created/modified/deleted
Owner run created `task1_out/` (untracked) and `task1_out.zip`. No tracked file modified by this task.

## Frozen-path check
`15_frozen_paths.sha256` (src/physics, src/digital_twin.py, src/rl, models/registry.json, alembic/versions, research/danish_aau/config) was produced by the owner's script inside `task1_out.zip`; contents were not reviewed by the agent here. Working tree has no modified tracked files, so frozen paths equal HEAD.

## Data/licence limitations
Raw data stays local and ignored. Licence still unverified (manifest field only). Nothing uploaded by this task beyond test logs.

## Open items and exact owner action
1. Name the Windows regression test file (119 tests) so it can be run.
2. Optional: rerun the frontend under Node 22.20.x, and send the output of `npx vitest run src/components/DashboardSidebar.readonly.test.tsx` to get the failure cause.
3. Optional: run Postgres tests against a throwaway test DB if you want them counted.
4. Decide whether the 4 backend + 5 frontend failures are accepted as the baseline of record.
5. `task1_out/` and the three stray untracked scripts remain; no action taken.

## Dependencies now unlocked (do not start)
Task 5 prerequisites (Tasks 2-4) still pending; Tasks 2, 3, 4 may start (raw data present, licence/processing authorisation to be confirmed by owner).
