# Task 30 report: fleet view (stretch)

## Gate
The spec says to build this only if the asset model supports several facilities. It does: `Facility` is its own table and `Asset`, sensors, alerts and readings carry a `facility_id`. The sites below are simulated, so no database rows are created or read.

## What changed
- **Backend (`api/plugins/fleet.py`, `src/fleet/`)**: `GET /api/fleet/sites` (any signed-in role, existing `state` rate limit) runs five **simulated** sites through the same digital twin as `/api/state` (throwaway twin, `live=False`; the live twin is never advanced). Sites are parameter sets inside the what-if scenario bounds: temperate, hot and dry, cold, hot and humid, peak load. Ranks (lower is better) for PUE, carbon and **simulated alert conditions**, plus an overall rank (sum of ranks, ties by id; ties share a rank).
- **Frontend (`features/fleet-view/`, route `/fleet`, Explore group)**: five ranking cards, sort by overall / PUE / carbon / alert conditions, drill-down detail panel, "Open in the What-if lab" link (carries load and ambient temperature). The selected site is the site context (`useSite()`), kept in the address as `?site=`; an unknown site is ignored. Loading, error and retry use the Task 20 `StandardBoundary`.

## Honesty rules held
- Every card says "Simulated"; the page label says "Not real facilities"; site names are "Simulated site A..E".
- "Alert conditions" are rule checks on the simulated state (outlet over limit, inlet outside its range, drought override), stated on the page, not recorded alerts.
- Carbon uses the flat assumed intensity when no carbon file is loaded, so carbon ranks reflect energy use only; the page says so.

## Assumptions
- Site parameters are my choice (documented in `src/fleet/sites.py`); the roadmap gave none. Only the hot-and-dry site trips a condition (the drought override), so the alert ranking has four tied sites.
- The site context is exported (`useSite`) but no other page reads it: existing pages were not edited. The lab link does not carry water stress (the lab holds it at 0).

## Tests (real output)
- `tests/test_task30_fleet.py`: `passed 13, failed 0` (ranking ties, determinism, no input mutation, rule checks at their limits, sites within scenario bounds, the drought site). Run on a small stand-in runner (no pytest here).
- Frontend: `features/fleet-view` (model + page, 17 tests) plus `registry.test.ts` and `components.test.tsx`: `Test Files 4 passed · Tests 42 passed`. ESLint clean, no `tsc` errors in the new folder. `registry.test.ts` ran with a temporary stub of the missing `src/runs/schema.ts` (not shipped), as in Tasks 20 and 24.
- `registry.test.ts` edited: `fleet-view` added to the shipped-feature list.

## Not verified
- `tests/api/test_task30_fleet_api.py` (401 without a token, five labelled sites over HTTP, live twin not advanced) was NOT run: no FastAPI, SQLAlchemy or pytest here.
- The uploaded repo has no `src/runs/`, so `npm run build` and `bundleScan` still fail before and after this change.
- No browser: the card grid at 360 px is untested.
