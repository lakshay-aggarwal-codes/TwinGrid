# Task 4 — FE-001 Frontend static correctness + physics-derived set-point range          Status: PARTIAL
Base: uploaded `TwinGrid-main.zip` (tagged `baseline` in a fresh git repo; owner's working copy not checked, `git status` / `git log -1 --oneline` not seen)     Date: 2026-10-20     Environment: no network, `npm ci` aborted (npm "Exit handler never called", node_modules incomplete), so `tsc`, `eslint`, `vitest` and `vite build` could not run. TypeScript 6.0.3 was available globally, but without the project's dependencies it cannot typecheck.

## Summary
The what-if lab's set-point range, default, slider, number box, validation and help text now come from the server's `setpoint_check.actuator_range_C` instead of the fixed 5 to 15 / default 7. While the range is unknown the lab shows a loading state; if it cannot be read it shows an unavailable state and runs nothing. Steps 1 to 3 (measure and fix the historical 16 `tsc` errors and 3 lint warnings) were NOT done: they need the real toolchain. None of the new or changed tests have been run.

## Acceptance checklist
| Criterion | Status | Evidence |
|---|---|---|
| `npm run verify` exits 0 | NOT RUN | needs `npm ci`; commands below |
| Zero new suppressions | met | `grep -rn "eslint-disable\|@ts-ignore" src \| wc -l` = 16 on baseline and after |
| Lab range from physics/backend, not a legacy constant | met in code, unrun in tests | `model.ts` has no set-point bound; `useSetpointRange()` reads `setpoint_check` |
| Slider, validation, help text read the same source | met in code | `Controls.tsx` `boundsOf()`; `LabPage.tsx` passes `range` to `Controls`, `url.ts`, saved-scenario load |
| Loading / unavailable state while range unknown | met in code, unrun | `LabPage.tsx` `StateBoundary`; tests in `LabPage.test.tsx` |
| Range tests for legacy-0 and 1 (2 if exposed) | written, unrun | `setpointRange.test.ts`, `LabPage.test.tsx`. Physics 2 is not exposed: `actuator_range_C` raises for it (RL env refuses version 2), so the backend sends no range and the lab shows "unavailable". |
| Legacy 5 to 15 no longer appears | written, unrun | physics-1 tests assert slider 16 to 25 and no value below 16 requested |

## Changed files
- `what-if-lab/model.ts` - removed fixed set-point bound and default 7; added `SetpointRange`, `setpointRangeOf`, `defaultInputs`, `snapSetpoint`; `normalise` takes the range. Default = the backend's own what-if default (7) clamped into the range: 7 under legacy-0, 16 under physics 1. No new constant beyond that existing default.
- `what-if-lab/useLab.ts` - `useSetpointRange()` (one fetch, 10 min stale).
- `what-if-lab/url.ts` - `parseLabUrl` / `withLabParams` take the range.
- `what-if-lab/Controls.tsx` - set-point control uses the range; adds a source line (`lab-setpoint-source`).
- `what-if-lab/LabPage.tsx` - gate component plus `LabBody`; saved scenarios are snapped into the current range on load; the "Baseline = backend defaults" button is now "Baseline = default inputs" (under physics 1 the default is not 7).
- `what-if-lab/logic.test.ts`, `LabPage.test.tsx` - updated for the range-aware API; new physics tests.
- `what-if-lab/setpointRange.test.ts` - new.
- `docs/roadmap/task-reports/TASK_4_PLAN.md`, `TASK_4_REPORT.md`.

## Commands run
- `git init; git add -A; git commit; git tag baseline` - ok.
- `npm ci` in `twin-stream-insight-main` - FAILED (no network; npm crashed). Nothing below that depends on it ran.
- TypeScript `transpileModule` on the 8 changed/new files - 0 syntax diagnostics. This is NOT a typecheck.
- Ad-hoc node script (not vitest) running the pure `model.ts` / `url.ts` logic with `setpointCheckOf` copied verbatim from the real file: the checks in `setpointRange.test.ts` and the updated `logic.test.ts` assertions - all passed.
- `grep -rn "eslint-disable\|@ts-ignore" src | wc -l` - 16 before and after.

## Pre-existing failures observed
None observed (toolchain did not run). The historical 16 `tsc` errors and 3 lint warnings are unmeasured here.

## Not run / blocked
Run from the repo root in PowerShell after applying the ZIP:
```
cd twin-stream-insight-main
npm ci
npm run typecheck 2>&1 | Tee-Object ..\tsc_errors.txt
npm run lint:ci   2>&1 | Tee-Object ..\lint_warnings.txt
npm run test
npm run build
```
Paste `tsc_errors.txt` and `lint_warnings.txt` and I will fix each at its source (steps 2 and 3).

## Decisions and defaults used
- Range source: `GET /api/optimizer/baseline-recommendation` `predicted.setpoint_check` (card step 4 fallback; no endpoint exposes a what-if range).
- Probe context: the backend's what-if defaults.
- Under physics 1 the default set-point is the bottom of the range (16), the nearest in-range value to the backend default 7.

## Requested cross-task changes
**Backend (blocks the lab under physics 1).** `GET /api/whatif` validates `chilled_water_temp` against `SR.CHILLED_WATER_TEMP_BOUNDS` = 5 to 15 (`api/routes/digital_twin_routes.py`, same bounds in `api/plugins/whatif.py`, `api/schemas/runs.py`, `api/plugins/capacity.py`, `api/plugins/economics.py`). `PHYSICS_VERSION` defaults to `"1"` (`src/versions.py`), whose actuator range is 16 to 25 (`src/rl/env.py`). Read from the code, not run: every lab request at 16 to 25 would get a 422, so with this frontend the lab shows an error state for every run until the backend accepts the same range the proposals endpoint does (`rules.accepted_chilled_range_C(SR.CHILLED_WATER_TEMP_BOUNDS)`, which is the union 5 to 25). `Query(ge=, le=)` is static, so this needs a per-request check. No task in §6 owns these files; needs an owner.

## New limitations or risks
- Unrun code: type errors or test failures are possible. In particular `LabPage.test.tsx` mocks `../optimizer-approvals/api` and assumes `StateBoundary` renders the `loading` message text.
- If the baseline-recommendation has no selected controller, `predicted` is null and the lab shows "unavailable" (no guessed range).
- One extra request on opening the lab (two twin simulations server-side, counted against the `whatif` rate limit).
- Saved scenarios and links made under another physics are snapped into the current range on load.

## Next tasks unblocked
None directly. Task 21 (CI hardening) needs `npm run verify` green, which needs steps 1 to 3 here.
