# Task 17 report: alerts centre and incident workflow

## What changed
- **Backend.** `api/plugins/alerts_workflow.py`: `GET /api/alerts/inbox`, `GET /api/alerts/{id}/events`, operator-only `PATCH /api/alerts/{id}`
  (status, assignee, note; one atomic `alert_updated` audit row). Lifecycle rules are a pure module, `src/alert_workflow.py`.
  Every write goes through new functions in `api/repositories/data_repository.py` (ADR 006 gate untouched). Migration
  `20261005000000` is additive (4 nullable `alerts` columns, new `alert_events` table).
- **Frontend.** `src/features/alerts-centre/`: inbox with severity/status filters (icon + text + border style), bulk acknowledge
  (open alerts only, one at a time, partial failures reported), per-alert detail with assignee, notes and incident timeline,
  link to the facility view and to Replay at the alert's time (`/replay?t=`), header widget with toast, live-region
  announcement and optional sound (off by default), `?alert=<id>` deep link, viewer = read-only.

## Assumptions
- Alerts carry **no rack**, so the 3D link opens the whole facility (the page says so); nothing is guessed.
- The stored state is the nullable `status` plus the legacy `acknowledged` flag, so old rows and `POST /acknowledge` keep working.
- `alert_updated` is not added to `audit_service.EVENT_MODES` (a test pins that table); it is written in atomic mode.
- The rate limit reuses the `alert_ack` class (`api/config.py` is off limits). An assignee must be an existing operator.
- Filters run in the browser over the latest 200 alerts; the API filters exist for other clients.
- Also edited: `models/db_models.py` (ORM must match the migration), `api/repositories/data_repository.py`, and
  `tests/test_alembic_chain.py` (head moves M5 to M6; assertions otherwise unchanged).

## Test results
Nothing could be executed here: the sandbox has no network, so neither the Python nor the npm dependencies could be installed.
Only these ran, and passed: `py_compile` on every new/changed Python file; a TypeScript syntax parse of every new `.ts/.tsx`
file; a direct run of the pure lifecycle module (`effective_status`, `check_transition`).
Tests written, not run: `tests/test_task17_alert_workflow.py`, `tests/api/test_task17_alerts_workflow.py` (permissions, every
transition, audit rows, assignee rules, inbox filters, timeline, migration up/down), and in the feature folder
`logic.test.ts`, `api.test.ts`, `AlertsPage.test.tsx`, `AlertWatcher.test.tsx`.

## Not verified
- `pytest`, `ruff`, `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build` were not run (see above); the new tests may need small fixes.
- The Alembic round trip and `alembic check` (ORM equals migration) were not run.
- `tests/test_task9_api_reference.py` needs `docs/api/` (absent from this ZIP) and cannot be regenerated without running the app.
