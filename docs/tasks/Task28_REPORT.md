# Task 28 — Predictive maintenance and work orders

**Claim:** per-asset health and degradation trend from stored simulated telemetry, and maintenance work orders (create by hand, from an alert, or from a health warning; operator/admin only; status flow; audit). There is **no remaining-life estimate**: nothing valid exists to produce one, and the UI says so.

## What changed
- `src/maintenance_health.py` (pure): per sensor, share of invalid samples, latest value vs the valid range, and an ordinary-least-squares trend as the share of the valid range moved over the window; status `ok` / `watch` / `warning`, and `no_data` (NOT MEASURED) under 12 valid samples. An asset is its worst sensor. `REMAINING_LIFE` is `available: false` with the reason.
- `src/work_orders.py` (pure): flow `open -> in_progress -> done`, `in_progress -> open`, cancel from open or in progress, done and cancelled final; roles (viewer reads, operator or admin writes); `origin` is `simulated` for an alert- or health-sourced order, `manual` otherwise.
- `alembic/versions/20261008000000_t28_work_orders.py`: two new tables (`work_orders`, `work_order_events`), additive, downgrade drops them. Models added to `models/db_models.py` (as Task 19 did). `tests/test_alembic_chain.py` head and order pins moved to the new revision.
- `api/plugins/maintenance.py`, `api/repositories/work_order_repository.py`: `GET /api/maintenance/health`, `GET|POST /api/maintenance/work-orders`, `GET|PATCH /api/maintenance/work-orders/{id}`, `POST .../status`. Atomic audit rows `work_order_created`, `_updated`, `_status_changed`; a refused role writes `permission_denied`. An unknown alert, asset or sensor is a 404 and nothing is recorded. Rate limits reuse `telemetry_read` and `alert_ack` (`docs/env/Task28.md`).
- `features/maintenance/` (`/maintenance`, Operate group): health table with a glyph and a word per status, trend line plus a sentence, a "Remaining life: not available" statement, assets without sensors listed as NOT MEASURED, the existing `/api/equipment/health` shown as methodology on a proxy dataset, a creation form (by hand, from an alert picked from the inbox, or prefilled from a health row), and the work-order list with the server's allowed moves. `features/registry.test.ts` list gained `maintenance`.

## Assumptions
- The only asset with telemetry is the facility-level one (five sensors); zones and racks have none, so they show NOT MEASURED. There is no per-rack health.
- Thresholds (5 % / 20 % invalid, 10 % / 25 % of range, 12 samples) are my choices, returned in the response, not a standard. Health is a data-health and drift indicator, not a failure prediction.
- No DELETE: cancelling retires an order and keeps its history. The UI exposes create and the status flow; the PATCH route (title, description, priority, assignee) exists and is tested but has no form yet.
- An order from a health row records the asset (and sensor) the user chose; the server checks they exist, it does not re-judge the health status.
- Built on the repo ZIP plus your Task 26 and 27 ZIPs; only `registry.test.ts` is shared with them.

## Test results
- `tests/test_task28_rules.py`, pure, under a small pytest shim (`pytest` is not installed): `passed 40, failed 0`. Golden: a +1 per 5 min ramp over 40 samples gives 288 per day, 39 over 3.25 h, 39 % of a 0..100 range, `warning`; fewer than 12 valid samples is `no_data`; every transition pair is covered.
- Frontend `model.test.ts` under Node 22 with an `expect` shim: `passed 13, failed 0`. Node type-strip parse of every changed `.ts` file: 0 errors. `py_compile` clean; `audit_alembic_graph.py`: 14 revisions, one chain.
- Written, not executed: `tests/api/test_task28_work_orders.py` (CRUD, permissions, audit, health endpoint), `tests/test_task28_migration.py` (structure, SQLite round trip, existing rows survive), the changed `test_alembic_chain.py`, and `MaintenancePage.test.tsx` (creation flow from a health row, from an alert, by hand; viewer; status flow).

## Not verified
- `pytest`, `ruff`, `alembic check` (ORM equals migration), `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build`, `bundleScan`: no installed toolchain and no network. All `.tsx` files unparsed.
- The plugin and routes were never imported or called (FastAPI and SQLAlchemy missing here).
