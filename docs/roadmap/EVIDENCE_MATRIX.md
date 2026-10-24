# Evidence matrix (Task 32, 2026-10-21)

Every acceptance item of the programme, mapped to code, test, run output, or an explicit blocker. **No release-candidate gate
(playbook Task 31) has been recorded, so there is no `RC_REPORT.md` and no overall verdict.** `evidence/status.json` is not
created: it must be filled from Task 31's real results, and there are none.

Columns: *Code* = exists in this tree. *Run output* = a recorded run of its tests or of the feature on a real stack. A dash means none.
Task reports are in `docs/roadmap/task-reports/` (each carries an "L4 update" section dated 2026-10-24; a report is PARTIAL or BLOCKED only where its status line still says so). Backend pytest evidence: one full owner run, 5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed (`C:\twlogs\pytest_full_final.txt`, 2026-10-24).

## Journeys (playbook §9)

| ID | Journey | Code | Run output | Status |
|---|---|---|---|---|
| J1 | Anonymous demo | `api/plugins/demo_session.py` (`DEMO_PUBLIC_ENABLED`, off by default); Task 13 | — | **Open**: no frontend entry point; backend not run. |
| J2 | Access request | `api/plugins/access_requests.py`, `src/access/*`; admin queue `features/admin-console/AccessPanel.tsx` (Tasks 9, 12) | — | **Open**: no public request form in this tree; nothing run end to end. |
| J3 | Owner decision on a phone | `src/notify/*` (approve/deny links by email; Task 10) | — | **Blocked**: needs a real mailbox; a file outbox exists for development. |
| J4 | Activation | `src/access/tokens.py`, `service.py` | — | **Open**: not run. |
| J5 | "Why is this red?" with cited evidence and honest unknowns | `src/copilot/*`, `api/plugins/copilot.py` (Task 14); `features/assistant/*` (Task 15) | — | **Open**: frontend gates for Task 15 not run; rule-based, no language model. |
| J6 | History with gaps | `telemetry/history/backfillMerge.ts` and tests (Task 23); `docs/roadmap/RT-001.md` (Task 8) | 11 pure merge tests ran under a stand-in runner (Task 23 report) | **Open**: browser journey not run. |
| J7 | ML status matches the ledger | `docs/CLAIMS.md` C-06..C-08, `docs/model_cards/*`, registry truth (Task 6), provenance (Task 7) | — | **Open**: ledger text matches the registered PPO outcome C; the page-to-ledger check was not run. |

## Definition of done (playbook §9)

| Item | Evidence | Status |
|---|---|---|
| Required CI jobs green and blocking | `.github/workflows/ci.yml`: `frontend-e2e` and `frontend-contract` carry `continue-on-error: true`; no recorded green run | **Not met** |
| One Alembic head | 15 revisions, one head `20261101000000` (computed from the files on 2026-10-21; `alembic check` not run) | **Met in source; check not run** |
| No skipped tests | Backend: 3 skips (each with a printed environment reason) and 9 strict xfails (one open defect, L1) in the full run 2026-10-24. Frontend vitest skip list: not pasted | **Partial** (backend met; frontend not shown) |
| Authorization matrix covers every route and token type | `tests/authz_matrix.py`, `tests/test_authz_matrix.py`: 183 tests passed, also in the full run 2026-10-24 | **Met in a local run** (CI job not shown, L6) |
| Every ML number links to a reproducible artefact | `reports/runs/*` manifests with `scripts/repro.py verify`; stored comparison is `baselines-v4`, which predates the `baselines-tuner/3` re-tune; `baselines-v5` is created on the owner's machine (Task 17) and is not here | **Partial** |
| PPO reported per its registered result | README, JUDGES Q6, CLAIMS C-08: outcome C, claim allowed: none | **Met in text** |
| Carbon labelled assumed | `src/carbon_provider.py`, `src/carbon_label.py`, `tests/test_carbon_label_guard.py` (27 cases ran under a stand-in runner); legacy API flag still means "a file is loaded" | **Partial** |
| No forbidden claim anywhere | `tests/test_task33_claims.py` (8 tests passed under a stand-in runner); `grep -rniE "production-ready|calibrated|saves? energy" README.md docs/*.md` read line by line: every hit is a negation, a "not calibrated/uncalibrated" statement, a "we do not claim" answer, or the forbidden-word list itself | **Met for README and docs/*.md; UI strings checked only by the same test** |
| Final verdict by Task 31 | none recorded | **Blocked** |

## Not run, and why this matrix cannot be better
No Docker, Postgres, browser, node_modules or network were available while Tasks 1 to 32 in this series were produced, so every
journey and gate above needs a run on your machine. Order that closes most rows: Task 21 (CI and contract fixtures), then the gates
listed in each task report, then Task 31.
