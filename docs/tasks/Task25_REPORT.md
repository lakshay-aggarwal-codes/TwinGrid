# Task 25 — Energy cost and tariff model

**Claim:** cost of a simulated day under an illustrative tariff, plus saving vs the default baseline in cost terms. Not a quote, not calibrated, not a bill.

## What changed
- `src/economics/tariff.py` (pure): `Tariff` (currency label, off-peak/peak rate, peak window incl. midnight wrap, demand charge per kW per billing period, billing days) with validation; `daily_cost` (peak/off-peak kWh, energy cost, prorated demand cost, total), `flat_hourly_profile`, `savings` (baseline - scenario, percent `None` when baseline cost is 0).
- `api/plugins/economics.py`: `GET /api/economics/summary` (auth required; tariff and scenario as bounded query params; default scenario/tariff = backend defaults). Response carries `label` "illustrative tariff, not a quote" (user-entered rates: "... still not a quote"), `estimate_label`, `origin: simulated`, `basis`, `currency_note`, both cost breakdowns, `savings`, `carbon_data_is_real`. Rate limit `RATE_LIMIT_ECONOMICS` (default `12/minute`, `docs/env/Task25.md`).
- `twin-stream-insight-main/src/features/economics/` (slot `dashboard`, order 50): card (total, energy and demand lines, worded saving "Saves / Costs more / Same", label, "How this is computed"), tariff settings drawer (validated, nothing clamped, kept in this browser, reset to defaults), API client + zod schema, loading/error states via `StateBoundary`.
- `features/registry.test.ts`: list gained `economics` (the test asks for it).

## Assumptions
- The what-if run holds inputs constant, so its energy is spread evenly over 24 h; peak demand = that even hourly power. No separate peak is modelled (stated in `basis`).
- Baseline = backend default what-if; card scenario = the current simulation sliders. Each call is two 24 h twin runs (one if the scenario equals the default), hence the 12/minute limit and an 800 ms input debounce.
- Default rates (0.08 / 0.18 per kWh, peak 16-21, 12 per kW-month, 30 days) are placeholders chosen for illustration, not taken from any utility.
- Currency is a label; nothing is converted. No migration, no new dependency.

## Test results
- `tests/test_task25_tariff.py`: `pytest`, `fastapi` and `ruff` are not installed here and cannot be installed (no network), so it ran under a small pytest shim with fastapi and the twin service stubbed: `passed 29, failed 0` (golden: 100 kWh/h flat = 242.00 energy + 40.00 demand = 282.00; uneven profile = 57.20; saving 28.20 = 10.0 %). `py_compile` clean. `ruff` not run: a few lines exceed 120 characters (E501 is ignored, but `ruff format --check` may want them rewrapped).
- `src/features/economics/tariff.test.ts` ran under Node 22 with an `expect` shim, in UTC and Asia/Kolkata: `passed 9, failed 0`. Node type-strip parse of every changed `.ts` file: 0 errors.
- Written, not executed: `EconomicsCard.test.tsx`.

## Not verified
- `ruff check`/`ruff format --check`; `vitest`, `tsc`, `lint:ci`, `build`, `bundleScan` (no installed toolchain); all `.tsx` files (no parser available).
- The plugin and route were never imported or called (fastapi missing); only `compute_summary` was exercised, with a fake twin.
