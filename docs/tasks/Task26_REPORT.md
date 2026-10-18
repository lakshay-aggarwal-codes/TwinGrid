# Task 26 — Capacity planner

**Claim:** facility headroom (power, cooling, thermal margin) and an "add N racks at X kW" what-if, run on the digital twin, shown as a table with a verdict and as a 3D zone overlay. Everything is labelled "model-based estimate" on simulated data. It is not a design sign-off.

## What changed
- `src/capacity/planner.py`: `evaluate(make_twin, scenario, plan)` runs the twin twice (as is, and with the load added) and returns headroom, status (`ok` / `tight` / `exceeded` / `unknown`), a verdict (`fits` / `fits_with_little_margin` / `does_not_fit`) and whole racks that fit by power and by cooling. Limits come from the twin: rated IT power, the plant's own (derated) cooling capacity from `last_balance`, and the safety envelope's outlet limit.
- `api/plugins/capacity.py`: `GET /api/capacity/headroom` (auth required, bounded query params, `RATE_LIMIT_CAPACITY`, default `12/minute`, `docs/env/Task26.md`). Read-only.
- `features/capacity/`: `/capacity` page (plan form validated without clamping, verdict, table with a glyph and a word per status, racks-that-fit line, "How this is computed"), and a `facility-inspector` slot widget with the headroom overlay switch and legend. The overlay fetches only while it is on.
- `three/headroomOverlayStore.ts` (named so it cannot clash with `HeadroomOverlay.tsx` on a case-insensitive filesystem), `three/HeadroomOverlay.tsx`, one line in `three/Facility.tsx`: each zone floor is tinted with the plan's worst status and labelled with an even share of the facility headroom. The plane is not raycastable.
- `features/registry.test.ts`: list gained `capacity`.

## Assumptions
- The backend has no per-rack or per-zone model, so headroom is a facility total. The overlay tints every zone the same and labels an even split across zones, stated on screen as an assumption.
- Added racks are extra constant IT load on the existing cooling plant (capacity pinned to its design value) and air handling; above the rated IT power the twin's airflow stays at its full-load value. The twin has no "extra load" input, so the load is expressed as a larger `max_it_power_kw` at the utilisation that gives base IT + N x X kW.
- "Tight" = under 10 % of a limit free, or under 3 °C thermal margin. These are model choices, stated in the response, not a standard. Power headroom is against the twin's rated IT power (500 kW by default), not a utility feed.
- The scenario is the current simulation sliders (same as the economics card). Racks-that-fit counts power and cooling only; thermal is checked for the requested plan, not searched. Physics legacy-0 has no cooling capacity, so cooling shows "not modelled".

## Test results
- `tests/test_task26_capacity.py` ran against the real twin (physics v1, fixed start time) under a small pytest shim: `passed 40, failed 0, skipped 1` (skipped: the plugin test, FastAPI is not installed here). Golden: default scenario IT 395.0 kW, power headroom 105.0, cooling 155.0 (capacity 550.0), thermal margin 8.26 °C; +10 racks at 8 kW = 475 kW, power 25.0 (tight), "fits with little margin"; +20 = 555 kW, "does not fit"; hot day (45 °C) cooling capacity 495.0; identical inputs give identical output.
- `model.test.ts` and `headroomOverlayStore.test.ts` ran under Node 22 with an `expect` shim: `passed 28, failed 0`. Node type-strip parse of every changed `.ts` file: 0 errors. `py_compile` clean.
- Written, not executed: `CapacityPage.test.tsx`, `OverlayControl.test.tsx` (including the overlay toggle test).

## Not verified
- `pytest`, `ruff check` / `ruff format --check`, `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build`, `bundleScan`: no installed toolchain and no network. All `.tsx` files unparsed.
- The plugin and route were never imported or called (FastAPI missing). The 3D overlay was never rendered in a browser (colour, label placement, `Html` from drei).
