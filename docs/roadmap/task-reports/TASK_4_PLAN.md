# Task 4 plan (FE-001)

Owned files only: `twin-stream-insight-main/src/features/what-if-lab/*`.

1. Range source: `GET /api/optimizer/baseline-recommendation` (any signed-in user) returns `predicted.setpoint_check.actuator_range_C`. It is the field the recommendation form reads (`optimizer-approvals/model.ts` `setpointCheckOf`). No endpoint exposes a what-if range directly, so the lab reads this one and adds no constant.
2. `model.ts`: drop the fixed `setpointC` bound; add `SetpointRange`, `setpointRangeOf`, `defaultInputs(range)`, `snapSetpoint`; `normalise(i, range)`.
3. `useLab.ts`: `useSetpointRange()`. `url.ts`: range-aware parse and serialise. `Controls.tsx`: slider, number box, validation and help text all read the same `range`.
4. `LabPage.tsx`: gate (loading, unavailable) around the existing page body.
5. Tests: update `logic.test.ts` and `LabPage.test.tsx`; add `setpointRange.test.ts`.
6. Verify: `npm run verify`. Not runnable in the build sandbox (no network, `npm ci` failed): see the report.
