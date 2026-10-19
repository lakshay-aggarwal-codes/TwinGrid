# Task 14 (TwinGrid roadmap) — Provenance and honesty labels everywhere

> File name: `docs/tasks/Task14_REPORT.md` belongs to an older task list ("Replay and time travel") and is NOT touched.
> The roadmap's earlier reports for Tasks 1, 2 and 4 were written as `Task1/2/4_REPORT.md` and overwrote same-numbered reports of that older list in this repo; this ZIP adds copies under unique names (`Task1_physics_aware_policies_REPORT.md`, `Task2_physics_aware_tuning_REPORT.md`, `Task4_baseline_tests_REPORT.md`). Restore the originals from git (see chat).

## What was missing (verified in the uploaded zip)
- Evaluation view: no executed physics (the API dropped `physics_version_executed`), no carbon row in the identity strip and no fallback flag on the provenance strip, hard-constraint metrics were plain columns, `hard_constraints`/`selection` ignored, and `schema_version: 2` (new reports, A2) was rejected as a contract violation.
- Recommendation card: no provenance strip, no evidence note, and a hardcoded 5..15 C input range that rejected the baseline's own physics-1 recommendation (16..25 C).

## What changed
Frontend (`twin-stream-insight-main/`): `src/evaluation/{schema,model,testFixtures}.ts`, `src/components/evaluation/{EvaluationView,HardConstraintPanel}.tsx`, `src/features/optimizer-approvals/{model.ts,EffectTable.tsx,RecommendationCard.tsx}`, tests, and docs (`docs/frontend/PROVENANCE_AND_FRESHNESS.md`, `docs/frontend/contracts/G-EVAL.md` addendum).
Backend: `api/services/evaluation_service.py` passes `physics_version_executed` through (additive, one key); `tests/test_evaluations.py` pins it (verbatim when present, absent for the legacy report).
Behaviour: see the table in `PROVENANCE_AND_FRESHNESS.md`. Key rules: a limit the report did not count is "not measured" and never "clean"; carbon missing is "not reported" never "real"; executed physics missing is "not reported" never the label; violations are words + icon shape, never colour alone; the panel sits before the metrics table and uses neutral styling for every state.

## Decisions
- Hard constraints are summarised from the per-policy test-set MEANS the API already serves (`0` = no episode violated; `>0` = at least one did). No new computation, no ranking, no "best" marker (the existing no-highlight tests still pass).
- The recommendation's accepted range mirrors the server's union (`min(5, lo)..max(15, hi)` from `predicted.setpoint_check`); the server still decides. Without a check the legacy 5..15 form is unchanged (older backend).
- Schema 2 is accepted; 3+ still fails with the path.

## Verification (audit sandbox, Node 22.22, Python 3.12; NOT your machine)
- Frontend `vitest`: whole suite 10 failed / 1953 passed, vs the pristine upload 10 failed / 1926 passed: **no new failures, +27 tests**. The 10 failures are identical before and after (TG-A-20).
- Changed areas: `src/evaluation`, `src/provenance`, `src/components/evaluation`, `src/features/optimizer-approvals` all pass; ESLint on them: only the 3 warnings that already exist on the pristine upload.
- `tsc`: no errors in any changed file; the 16 errors elsewhere are identical on the pristine upload (TG-A-20).
- `vite build --mode development` OK (3306 modules). The production build is blocked by the repo's own env check (needs deployment env vars): not run.
- Backend `tests/test_evaluations.py`: 26 passed.

## Not done / open
- Run page, report export and what-if lab views were not changed (TG-A-19 lists the legacy-range copies still in the what-if lab and sidebar).
- No browser/E2E run (Playwright not run); no manual keyboard or screen-reader pass: icon + text is by construction, not by test of an assistive technology.
- The frontend's own `typecheck` and 10 tests are red independent of this task (TG-A-20).
- Loading/error/disconnected states of the evaluation list/detail are the existing `StateBoundary` ones (already tested in `EvaluationScreen.test.tsx`); not re-tested here.
