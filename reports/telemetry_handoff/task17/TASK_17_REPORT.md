# Task 17 report: frontend individual telemetry readouts

**Status: Ready for review. Not verified by execution.** The sandbox had no `node_modules` and no network, so Vitest, ESLint and the repo `tsc` project were not run. Only a syntax-level `tsc` pass was possible; its only complaints came from unresolved third-party types (zod, vitest, vite), not from the new code.

## What was built (all new, all under `twin-stream-insight-main/src/features/dataset-telemetry/`)
| File | Purpose |
|---|---|
| `schemas.ts` | Strict zod schemas for the Task 8 record and the `rack_view` / `error` envelopes. No default/catch/coerce. |
| `model.ts` | Pure view model: value / not reported / missing / invalid / absent, provenance label, source-time text, historical label, group-power pointer. |
| `fixtures.ts` | **Synthetic** mock of the contract (3 racks, distinct values, a flagged value, a conflict-missing cell, an absent probe, a group pointer and a single-rack port). |
| `source.ts` | `DatasetTelemetrySource` interface plus the fixture source. No route path is invented; Task 16 supplies the real source. |
| `RackReadout.tsx`, `DatasetTelemetryPage.tsx` | Per-rack readout and rack selector (`/dataset-telemetry`). |
| `index.ts` | Feature module: route `/dataset-telemetry`, nav "Dataset telemetry", UX-gated to operator (Task 9 D-4: demo tokens refused). |
| `*.test.ts(x)` | Schema/fixture, view-model, page behaviour (including rack isolation, missing values, group power, a11y roles) and static source gates. |

## Rules honoured
- Only the selected rack's own envelope is rendered; no facility value, other rack or earlier value is ever substituted.
- Missing data reads `Not reported` (no row) or `No value` (source cell unusable); never a number.
- Imported data is labelled "Recorded dataset (historical), not live", source time with "timezone not established"; `stream=live` is never used (source gate test).
- Group power (racks 1-3, 4+6) shows a pointer with no value; only a single-rack port shows power.
- Own provenance view model; nothing under `src/provenance/`, `src/three/`, `src/contract/`, `facility-inspector/` or `App.tsx` was edited (G1-D8, Task 10 ownership plan). The simulated 36-rack view is untouched.

## Not done / open
1. **Real data source:** `apiSource.ts` now calls the Task 16 routes (`GET /api/datasets/{id}` and `/racks/{rack}`) with `facility_id` and `stream=import:<id>` on every call. It is used only when `VITE_DATASET_ID` and `VITE_DATASET_FACILITY_ID` are set; otherwise the synthetic fixture runs with a banner. Needs verification against a running backend.
2. **Attribution (CC BY 4.0 + modification statement):** rendered from the dataset record's `attribution_text` and `modifications_statement` when the API source is used.
3. **Checks to run on Node 22.20.x:** `npm run typecheck`, `npm run lint:ci`, `npm test`, `npm run build` (G1-R10: baseline already had 5 frontend failures).
4. `row_ordinal` base and `label_evidence` wording follow the contract's open questions; the UI shows them as recorded.
