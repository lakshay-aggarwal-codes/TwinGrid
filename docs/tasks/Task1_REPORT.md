# Task 1 — Foundation: extension points

## What changed
- **Backend:** `api/plugins/__init__.py` (`load_plugins`), one additive call in `api/main.py` after the routers. Tests: `tests/test_task1_plugins.py`, fixtures `tests/plugin_fixtures/` (test-only).
- **Frontend (`src/features/`):** `types.ts`, `registry.ts` (glob discovery, validation, role filtering), `roles.ts`, `commands.ts` + `useCommands.ts` (shared command registry), `Slot.tsx`, `FeatureNav.tsx`, `FeaturePage.tsx`, `FeatureRoutes.tsx`. Test-only example feature in `src/test/fixtures/exampleFeature/`.
- **Additive host edits:** `App.tsx` (feature routes above the catch-all), `DashboardSidebar` and `TwinHeader` (nav), `Index` (`dashboard` slot), `SidePanel` (`facility-inspector`), `TwinHeader`/`DashboardHeader` (`header-actions`), `AccountMenu` (`settings`). With no features, all render nothing.
- Docs: `docs/architecture/extension_points.md`.

## Assumptions
- There is no settings page and no navigation sidebar; `settings` is hosted in the account bar and nav in the controls sidebar and the live-twin header.
- Plugin routers get the core general rate-limit dependency; `setup` runs before `include_router` so a failing plugin adds no routes.
- `admin` is accepted as a `minRole` but the backend issues only viewer/operator, so admin-only items are hidden from everyone for now.

## Tests (real output)
- `pytest tests/test_task1_plugins.py`: `10 passed`. `ruff check`: `All checks passed!`
- `vitest run src/features`: `Test Files 2 passed (2) · Tests 30 passed (30)`
- Full vitest, before → after: `6 failed | 905 passed | 14 skipped` → `6 failed | 935 passed | 14 skipped`; the failing set is identical.
- Backend (api, smoke, startup, security, alembic): `26 failed, 545 passed` before and after, identical set (route-table walkers hit FastAPI's lazy `_IncludedRouter`).
- `npm run lint:ci`: exit 0, 0 warnings. `npm run typecheck`: 7 errors before and after, none in files touched.

## Not verified
- `npm run build` fails before and after: the uploaded zip has no `src/runs/` (`Runs.tsx` imports `@/runs/flag`, `@/components/runs/*`). The same gap causes the typecheck errors and `bundleScan` failures. Task 1's "build passes" could not be shown; re-upload with `src/runs/` or fix in Task 2.
- No browser, Docker or CI.
