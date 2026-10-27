# Evidence matrix (Task 32, 2026-10-21)

Every acceptance item of the programme, mapped to code, test, run output, or an explicit blocker. **No release-candidate gate
(playbook Task 31) has been recorded, so there is no `RC_REPORT.md` and no release verdict.** The readiness assessment from existing evidence is **PARTIALLY READY** (`docs/roadmap/task-reports/R_L9_REPORT.md`, R3 Task 15). `evidence/status.json` is not
created: it must be filled from Task 31's real results, and there are none.

Columns: *Code* = exists in this tree. *Run output* = a recorded run of its tests or of the feature on a real stack. A dash means none.
Task reports are in `docs/roadmap/task-reports/` (each carries an "L4 update" section dated 2026-10-24; a report is PARTIAL or BLOCKED only where its status line still says so). Backend pytest evidence: the latest full owner run (R3 Task 12, 2026-10-26, Windows) is 5741 passed, 78 skipped (75 need Postgres, 3 are platform or client limits), 1 deselected, 0 failed; one of those three skips (the non-ASCII request id) now runs. It supersedes the run of 2026-10-24 (5676 passed, 3 skipped, 81 deselected, 9 xfailed, 0 failed). CI evidence: PR #87 at `cee2af9` (R3 Task 11, `R3_TASK_11_CI_EVIDENCE.md`). **Updated 2026-10-28 (R3 Task 14)**; rows not named below were not re-checked.

## Journeys (playbook §9)

| ID | Journey | Code | Run output | Status |
|---|---|---|---|---|
| J1 | Anonymous demo | `api/plugins/demo_session.py` (`DEMO_PUBLIC_ENABLED`, off by default); Task 13 | `viewer-workflow.spec.ts` `[demo]` tests and the 1-minute demo-session drill passed on the owner's machine (`R_L7_REPORT.md`); the demo may ask the assistant (R3 Task 5) | **Run locally**: not in CI (`frontend-e2e` is advisory and red). |
| J2 | Access request | `api/plugins/access_requests.py`, `src/access/*`; request form and activation page; admin queue `features/admin-console/AccessPanel.tsx` (Tasks 9, 12) | `viewer-workflow.spec.ts` passed 6 of 6 across passes; axe passed on the request form and activation page (`R_L7_REPORT.md`, R3 Task 13) | **Run locally**: not in CI. |
| J3 | Owner decision on a phone | `src/notify/*` (approve/deny links by email; Task 10) | the two `[smtp]` tests passed over a local SMTP path; the mail-failure drill passed 3/3 (`R_L7_REPORT.md`) | **Blocked**: a real mailbox has not been tried. |
| J4 | Activation | `src/access/tokens.py`, `service.py` | covered by the `viewer-workflow.spec.ts` runs above; a malformed token gets the dead-link page (`R_L7_REPORT.md`) | **Run locally**: not in CI. |
| J5 | "Why is this red?" with cited evidence and honest unknowns | `src/copilot/*`, `api/plugins/copilot.py` (Task 14); `features/assistant/*` (Task 15) | — | **Open**: the assistant drill AI-D-1 and AI-D-2 passed and AI-D-3 failed when `R_L7_REPORT.md` was written (dead "Explain this" on pages without the assistant host); its current state was not re-checked here. Rule-based, no language model. |
| J6 | History with gaps | `telemetry/history/backfillMerge.ts` and tests (Task 23); `docs/roadmap/RT-001.md` (Task 8) | 11 pure merge tests ran under a stand-in runner (Task 23 report); `drill_history_gap.sh` passed 9/9 on the owner's machine (`R_L7_REPORT.md`) | **Open**: browser journey not run. |
| J7 | ML status matches the ledger | `docs/CLAIMS.md` C-06..C-08, `docs/model_cards/*`, registry truth (Task 6), provenance (Task 7) | — | **Open**: ledger text matches the registered PPO outcome C; the page-to-ledger check was not run. |

## Definition of done (playbook §9)

| Item | Evidence | Status |
|---|---|---|
| Required CI jobs green and blocking | `.github/workflows/ci.yml`: `gate` requires `lint`, `types`, `test`, `test-postgres`, `audit`, `frontend` and `docker`; all green on PR #87 at `cee2af9`. `frontend-contract` was also green but still has `continue-on-error: true`; `frontend-e2e` has it and was red; Netlify deploy preview failing, cause not read. Branch protection is not applied (`docs/governance/BRANCH_PROTECTION.md`) | **Partial** |
| One Alembic head | 15 revisions, one head `20261101000000` (computed from the files on 2026-10-21; `alembic check` not run) | **Met in source; check not run** |
| No skipped tests | Owner's full run 2026-10-26: 78 skips, each with a printed reason: 75 are Postgres-gated (run in CI's `test-postgres`, which passed), 3 are platform or client limits (one since fixed). The CI `test` job fails on any skip and passed on PR #87. Frontend vitest skip list: not pasted | **Partial** (backend met; frontend not shown) |
| Authorization matrix covers every route and token type | `tests/authz_matrix.py`, `tests/test_authz_matrix.py`: 183 passed (R3 Task 9) and no failure in the full run 2026-10-26; the CI `test` job, which runs `tests/`, was green on PR #87 | **Met** (local runs; CI `test` job green) |
| Every ML number links to a reproducible artefact | `reports/runs/*` manifests with `scripts/repro.py verify`; stored comparison is `baselines-v6`, recorded on the current lock and the shipped `baselines-tuner/3` configs (manifest `dirty: false`); `repro.py verify baselines-v6` prints one expected `FAIL code_revision` after later commits (`R3_TASK_4_REPORT.md`); `baselines-v4` and `baselines-v5` are superseded | **Partial** |
| PPO reported per its registered result | README, JUDGES Q6, CLAIMS C-08: outcome C, claim allowed: none | **Met in text** |
| Carbon labelled assumed | `src/carbon_provider.py`, `src/carbon_label.py`, `tests/test_carbon_label_guard.py` (27 cases ran under a stand-in runner); legacy API flag still means "a file is loaded"; an Ember India importer exists and labels its flat curve as having no time-of-day shape (`R_CARBON_REPORT.md`: verdict PARTIAL, owner's install and demo mount open) | **Partial** |
| No forbidden claim anywhere | `tests/test_task33_claims.py` (8 tests passed under a stand-in runner); `grep -rniE "production-ready|calibrated|saves? energy" README.md docs/*.md` read line by line: every hit is a negation, a "not calibrated/uncalibrated" statement, a "we do not claim" answer, or the forbidden-word list itself | **Met for README and docs/*.md; UI strings checked only by the same test** |
| Final verdict by Task 31 | none recorded | **Blocked** |

## Not run, and why this matrix cannot be better
No Docker, Postgres, browser, node_modules or network were available while Tasks 1 to 32 in this series were produced; since then the
owner has run the suites, the drills, the accessibility spec and a CI pull request (R3, 2026-10-25 to 28), recorded above. Every journey
and gate not named above still needs a run on your machine. Order that closes most rows: Task 21 (CI and contract fixtures), then the gates
listed in each task report, then Task 31.
