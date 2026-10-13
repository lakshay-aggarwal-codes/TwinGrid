# Extension points (Task 1)

Later features add themselves; they do not edit shared files.

## Backend plugin: `api/plugins/<name>.py`
Export `router` (an `APIRouter`) and/or `setup(app)`. `api/main.py` calls `load_plugins(app, dependencies=_GENERAL_LIMIT)` once, after the core routers, so plugin routes get the same general request-rate window.
- Modules starting with `_` are ignored; the rest load in name order.
- A plugin that fails to import, exports a non-`APIRouter` `router`, raises in `setup`, or re-registers an existing `(path, method)` is skipped and logged (ERROR when `ENVIRONMENT=production`, else WARNING). Clients see nothing; the API still starts.
- `setup` runs before the router is included, so a failing `setup` adds no routes.
- Plugin middleware is added before the core middleware, so it sits inside them.
- Add no env vars here; a plugin that needs one documents it in its own `docs/env/Task<N>.md`.

## Frontend feature: `src/features/<name>/index.ts`
Default-export a `FeatureModule` (`src/features/types.ts`): `route`, `nav`, `commands`, `slots`. Discovered at build time with `import.meta.glob`.
- Route paths must not collide with core routes (`CORE_ROUTE_PATHS`; a test compares it with `App.tsx`). A bad module is rejected alone with a console warning.
- `minRole` (viewer < operator < admin) filters nav items, slot widgets and commands, and a route the role may not use renders the 404 page. UX only; the backend enforces roles.
- Slots: `dashboard`, `facility-inspector` (receives `{ rackId }`), `header-actions`, `settings`. Each widget is isolated by its own error boundary.
- Commands go into the shared `commandRegistry` (`src/features/commands.ts`, hook `useCommands`); ids must be unique.
- The `settings` slot sits in the account bar (there is no separate settings page yet).
