# ADR 009: two ways to acknowledge an alert (D-16)

## Status
Accepted (Task 16). Both routes are kept.

## Context
Two operator-only routes acknowledge an alert:

| Route | Code | What it writes |
|---|---|---|
| `POST /api/alerts/{id}/acknowledge` | `api/routes/anomaly_routes.py` -> `data_repository.acknowledge_alert` | the legacy `acknowledged`, `acknowledged_by`, `acknowledged_at` columns; one audit row `alert_acknowledged`; idempotent (a repeat overwrites who/when); no timeline event, `alerts.status` untouched |
| `PATCH /api/alerts/{id}` (`{"status": "acknowledged"}`) | `api/plugins/alerts_workflow.py` -> `data_repository.apply_alert_workflow` | the same legacy columns, plus `alerts.status`, plus an `AlertEvent` timeline row; one audit row `alert_updated`; enforces the lifecycle (`open -> acknowledged -> resolved`, re-open), a repeat is a 409 |

Both go through `data_repository` (ADR 006) and keep the legacy columns consistent, so they never disagree about whether an alert is acknowledged.

## Which one the UI uses
* Alerts centre (`twin-stream-insight-main/src/features/alerts-centre`, `api.ts`): **PATCH**. It is the only UI that shows or changes the full lifecycle, the assignee and the timeline.
* The older incidents list (`src/components/alerts/AlertRowItem.tsx` via `src/api/alerts.ts`, shown in `IncidentsPanel`): **POST**. It only knows new/acknowledged.

## Decision
Keep both. `POST .../acknowledge` is a compatibility route for the older list and for existing API clients; new UI work, and anything that needs the timeline, must use `PATCH`. Neither route is removed or changed by Task 16.

## Consequences
* An alert acknowledged through the POST route has no "status" timeline event; the alerts centre still shows it as acknowledged (it derives status from the legacy columns).
* If the older list is retired, the POST route can be deprecated with a `Sunset` header; that is a separate decision and needs an owner.
* The two routes have different repeat semantics (POST: 200 and who/when overwritten; PATCH: 409). A client must not assume they are interchangeable.
