# Task 15 — What-if lab

## What changed
**Backend** (no core file edited)
- `src/whatif_sweep.py`: pure, deterministic one-at-a-time sweep. Moves IT load (±0.10), ambient (±5 °C), chilled-water setpoint (±2 °C) and each other cooling mode, one at a time, around the scenario. Hard cap `MAX_SWEEP_RUNS = 12` (11 at most in practice; a side clamped onto the baseline is not run). Every number is `compute_whatif`'s own output; the module only subtracts the baseline. Thermal margin = `OUTLET_TEMP_MAX` − max outlet temperature.
- `api/plugins/whatif.py`: `GET /api/whatif/sensitivity` (auth required, same bounds as `/api/whatif`, no persistence option: ADR 007). Whole sweep runs as one `run_compute` unit (shared concurrency bound and timeout). Rate limit `RATE_LIMIT_WHATIF_SWEEP`, default `6/minute` (`docs/env/Task15.md`).
- Tests: `tests/test_task15_whatif_sweep.py` (determinism, caps, bounds, delta arithmetic, equality with the real twin), `tests/api/test_task15_whatif_sensitivity.py` (401/403, shape, determinism, 422s, edge cap, nothing persisted, 429 + Retry-After, env override, default 6/min).

**Frontend** (`src/features/what-if-lab/`, route `/whatif-lab`, nav "What-if lab")
- Sliders (IT load, ambient, cooling setpoint) with number boxes + cooling-mode radios; 400 ms debounce; runs through the existing `fetchWhatIf` (same `['whatif', params]` cache key as the current tab).
- Baseline (default = backend defaults, or pinned) vs scenario delta cards: energy, PUE, carbon (fallback label whenever the backend's `carbon_data_is_real` is false), thermal margin. Direction is a glyph plus a word; no good/bad colouring.
- Sensitivity tornado from the backend sweep, run on request, sorted by swing, with a "computed for other inputs" notice when the controls move.
- Save/compare scenarios (max 8, browser-only `localStorage`, damaged entries dropped), shareable URL (`load, amb, set, mode`, baseline `bload…`), CSV export (formula-safe).
- Everything is labelled "model estimate on simulated data".

## Assumptions / deviations
- The existing What-If tab was **not edited** (no Touches listed for this task); the lab is a new page beside it.
- Water stress is held at 0 (backend default) and the page says so; the four requested controls are the only inputs.
- Thermal-margin ceiling on the cards is 45 °C (`OUTLET_SCALE.max`, the same constant the 3D thermal scale uses); the sweep returns the backend's own `outlet_limit_C`.
- The sweep is on-demand, not automatic, because of the 6/minute limit.
- API tests live in `tests/api/` to use its fixtures.

## Test results (real output)
- Backend sweep logic `tests/test_task15_whatif_sweep.py`, run here with a minimal pytest shim and a stubbed `fastapi`: `11 passed, 0 failed` (includes the real-twin baseline and determinism tests). A real sweep took ~0.12 s for 11 runs.
- Frontend pure logic `logic.test.ts` (esbuild bundle + vitest shim): `35 passed, 0 failed` (debounce, delta math, URL round trip, saved, CSV, tornado on a captured real sweep).
- Server-render smoke of DeltaCards, Controls, SavedPanel: `3 passed`.
- `tsc` on lab files (deps absent, missing-module noise filtered): 0 errors.

## Not verified
- `pytest` (API tests need fastapi/httpx/sqlalchemy/slowapi, not installed), `ruff format --check`, `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build`: no network here. `LabPage.test.tsx` (15 RTL tests) and the 15 API tests are written but were not executed.
- slowapi's acceptance of a callable limit (`@limiter.limit(_limit)`) is expected but unconfirmed here; if it complains, use a fixed `"6/minute"` string.
