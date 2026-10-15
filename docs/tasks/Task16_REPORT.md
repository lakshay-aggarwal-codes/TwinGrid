# Task 16 — Executive dashboard and insights

## What changed
New feature `twin-stream-insight-main/src/features/executive-dashboard/` (auto-discovered; three widgets in the `dashboard` slot, which the Analytics page already hosts; no route, no nav, no backend change, no new dependency):
- **KPI cards**: PUE, IT energy, total energy, carbon, savings vs baseline controller. gsap counters write to the DOM node (no per-frame React state; instant under reduced motion). Sparklines of live PUE, IT power, total power and carbon intensity. Loading / error / stale / NOT MEASURED states.
- **Goal rings**: four goals (PUE, outlet temperature, 24 h energy, 24 h carbon), editable targets (keyboard, validated, Esc cancels), stored in this browser only. State is words + icon + dashed ring when over target.
- **Insights feed**: deterministic rules (`insights.ts`): PUE trend with IT/cooling-power comparison, PUE vs target, outlet peak vs target, unacknowledged alerts, fallback-carbon notice. Each item shows "Rule-based, not AI", its rule id and the data window used. No LLM call.
- `registry.test.ts`: shipped-features list updated to the six real features (it was missing `replay` and `what-if-lab`).

## Assumptions
- **No per-rack data exists**, so no insight names a rack. The driver sentence compares IT power and cooling power (PUE = total ÷ IT) and says "association, not a proven cause".
- **The backend stores no PUE or total-power history** (five sensor measurands only). PUE trend and sparklines use live frames received by this tab (ring of 1800, reset on a >60 s pause or a restarted `seq`); trend rules need 10 samples and 2 min and print the window.
- **Energy and carbon** = `GET /api/whatif` for the sidebar inputs (same query key as the What-If tab), labelled "model estimate on simulated data"; fallback carbon is labelled whenever `carbon_data_is_real` is not true. `/api/whatif` has no IT-energy field: IT energy = `total_water_L ÷ wue` (the backend's own WUE definition). Checked against the twin's internal per-step IT energy on two real runs (9480.000000000005 and 8400.00000000003 kWh, exact match); NOT MEASURED when WUE is 0.
- **Savings** = newest backend policy-evaluation report; baseline controller = its `rule` policy; compared = first PPO policy, else first other policy; one subtraction of the backend's `energy_kwh`. The report's `claim_allowed` and outcome are printed with it. With the current captured report this is `rule` vs `best_constant`, claim `none`, and the card says so. NOT MEASURED when no such pair exists.
- Default targets: PUE 1.30 (arbitrary starting value, labelled "default"), outlet 38 °C (the app's thermal warning level). Energy and carbon start unset rather than with an invented number.

## Test results (real output)
- `insights.test.ts` + `logic.test.ts` (fixed inputs, exact expected sentences; real `compute_whatif` captures and the real evaluation capture), run through a minimal vitest shim with tsx: `34 passed, 0 failed`.
- Server-render smoke of the three widgets (stubbed icon/gsap packages): `smoke ok` (values, labels, NOT MEASURED, loading, sentences).
- `tsc` on the feature files: no errors except those caused by absent `node_modules` (missing React types, `key`). It did catch, and I fixed, a union narrowing that fails under this repo's `strict: false`.

## Not verified
- `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build`, a browser: no network here. `components.test.tsx` (13 RTL tests) and the updated `registry.test.ts` were written but not executed.
- The e2e a11y spec on `/analytics` now sees these widgets; not run.
