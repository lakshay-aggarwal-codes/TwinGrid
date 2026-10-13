# Task 5: demo data and one-command demo

## What changed
- `scripts/demo_seed.py`: refuses unless `DEMO_MODE=true`; seeds facility (3 zones, 36 racks, 5 facility sensors), accounts `demo_viewer` / `demo_operator` / `demo_admin` (random passwords, printed once by the script, only bcrypt hashes stored), 24 h of simulated telemetry (1,440 samples via `ingest_samples`, `origin=simulated`), 3 simulation runs (same writers as `persist=true`, ADR 007), 3 alerts via `data_repository.save_alert` (ADR 006).
- `docker-compose.demo.yml` (overlay; `docker-compose.yml` untouched), `scripts/demo.ps1`, `scripts/demo.sh`: create `.env.demo` once, `up --wait` db/redis/API (migrations run on API start), run the seed, print URLs.
- Frontend feature `simulated-data`: "Simulated data" badge in slot `header-actions`, shown only when the live frame's `origin` is exactly `simulated`.
- `tests/test_task5_demo_seed.py`, `src/features/simulated-data/SimulatedDataBadge.test.tsx`, `docs/env/Task5.md`.
- Touched: `src/features/registry.test.ts`. The assertion "ships no feature yet" became "ships exactly `['simulated-data']`" (stricter, not weaker; it had to change because this is the first shipped feature).

## Assumptions
1. `admin` is seeded as the role string `admin` (registration only allows viewer/operator, so the seed inserts directly). The backend checks only `operator`, so today the admin demo account has viewer-level rights.
2. Telemetry goes into the `live` stream (the default of the history endpoints), on a 5-minute grid in the past; the live feed stamps wall-clock tick instants, so keys do not collide. Values are a fixed synthetic daily pattern, not plant-model output and not calibrated.
3. The 1.0 m per scene unit scale is unsigned; the seeded `frame_note` says so.
4. The 3 alerts are scripted illustrations ("Demo: ... (simulated)"), not detector output.
5. Re-run: same clock adds nothing; a later run adds only the new tail of telemetry. Existing accounts keep their (unrecoverable) passwords; reset with `down -v`.
6. Demo API runs with `ENVIRONMENT=development` via the overlay; not for real deployments.

## Test results
NOT RUN. This sandbox has no network and no Python/Node dependencies installed, so `pytest`, `ruff`, `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build` and the `bundleScan` test could not run. Only `python -m py_compile` on the new Python files passed.

## Not verified
- All new tests (backend and frontend) and the lint/type/build gates, as above.
- The Docker flow and both launch scripts (no Docker or PowerShell here).
- Demo seed alongside a running live feed, and a browser view of the badge.
