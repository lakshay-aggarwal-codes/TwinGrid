# Task 27 — Carbon-aware scheduling suggestions

**Claim:** the usual lowest-carbon window for a flexible load, from the hour-of-day carbon curve. With the flat fallback carbon signal it says "No carbon variation in current data" and claims no saving. Not a forecast, not marginal-emissions advice.

## What changed
- `src/carbon_schedule/windows.py` (pure): `plan` (best / worst / baseline windows on a 24-point curve, whole hours, windows may wrap midnight when "any time" is allowed, ties go to the earliest candidate), `suggest` (the response body and the honesty rules), `validate`.
  - Flat curve (the 475 gCO2/kWh fallback, or any flat series): status `no_variation`, headline "No carbon variation in current data", no window, no saving.
  - Hours filled by an assumption, or a series with no documented meaning (`semantic` unknown): status `unverified`, no window, no saving (same standard as `carbon_provider.format_carbon_reduction`).
  - Varying, documented, complete series: status `ok`, best window, emissions, saving vs the average of all allowed windows (or vs a reference start hour).
  - `profile=synthetic_demo`: a fixed artificial curve (mean 475, lowest 13:00), status `synthetic_demo`, labelled "SYNTHETIC DEMONSTRATION profile, not grid data" and never mixed with data.
- `api/plugins/carbon_schedule.py`: `GET /api/carbon/schedule` (auth required, bounded params, read-only, no twin run). Rate limit `RATE_LIMIT_CARBON_SCHEDULE` (default `30/minute`, `docs/env/Task27.md`).
- `twin-stream-insight-main/src/features/carbon-scheduling/`: dashboard card (slot `dashboard`, order 60): run length and load inputs (validated, never clamped), an off-by-default synthetic-demo checkbox, headline/message per status, window and saving only when allowed, a 24-bar strip (best window outlined, dashed when synthetic, text alternative), honesty label, "How this is computed", loading/error states via `StateBoundary`. The zod schema rejects a body that claims a window or saving without a supporting status.
- `features/registry.test.ts`: list gained `carbon-scheduling` (the test asks for it).

## Assumptions
- Built on the repo ZIP plus your uploaded Task 26 ZIP (`/api/capacity/headroom`, `features/capacity/`); nothing of Task 26 was changed except the shared `registry.test.ts` list.
- The curve is the carbon provider's hour-of-day mean by site-local hour: suggestions say which hours are usually lower, never a time on a particular date. Granularity is whole hours.
- Default baseline = average of all allowed windows (no assumption about when a user would otherwise run). The API also accepts `window_start`, `window_hours`, `reference_start_hour`; the card does not expose them yet (whole day, average baseline).
- The default load of 100 kW is a placeholder for the form, not a measurement. The load is hypothetical and says so on screen.
- The synthetic curve shape is arbitrary, chosen only to show a visible window.
- No migration, no new dependency, no secrets.

## Test results
- `tests/test_task27_carbon_schedule.py`, real `carbon_provider` signals from temporary CSVs, under a small pytest shim (`pytest` is not installed): `passed 35, failed 0, skipped 1` (skipped: the plugin test, FastAPI is not installed here). Golden: ramp series 300 + hour gCO2/kWh, 100 kW x 4 h: best 00:00 to 04:00, mean 301.5, 120.6 kg; average window 311.5; saving 4.0 kg = 3.21 %; flat fallback, flat loaded series, missing hours and undocumented series claim nothing; synthetic best window 12:00 to 15:00 for 3 h.
- Every response body is strict-JSON serialisable (checked for the flat, varying and synthetic cases).
- `model.test.ts` under Node 22 with an `expect` shim: `passed 7, failed 0`. Real React server render (react-dom, automatic JSX) of `HourStrip` (6 checks) and of the full card for all four statuses with `StateBoundary` and the query hook stubbed (13 checks): all passed. TypeScript syntax parse of every changed `.ts`/`.tsx`: 0 errors. `py_compile` clean.
- Written, not executed: `tests/api/test_task27_carbon_schedule_route.py`, `schema.test.ts`, `CarbonScheduleCard.test.tsx`, `registration.test.tsx`.

## Not verified
- `pytest`, `ruff check` / `ruff format --check`, `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build`, `bundleScan`: no installed toolchain and no network.
- The plugin and route were never imported or called (FastAPI missing); the HTTP tests, the zod schema and the card inside the real dashboard were never run.
