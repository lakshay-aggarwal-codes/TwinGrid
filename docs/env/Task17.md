# Task 17: alerts centre and incident workflow

No new environment variables.

| Setting | Used for | Default |
|---|---|---|
| `RATE_LIMIT_ALERT_ACK` | `PATCH /api/alerts/{id}` shares the existing alert-acknowledge limit class | `30/minute` |
| `RATE_LIMIT_GENERAL` | the two read routes (`GET /api/alerts/inbox`, `GET /api/alerts/{id}/events`) use the plugin default | `120/minute` |

## Endpoints (plugin `api/plugins/alerts_workflow.py`)

| Route | Who | Notes |
|---|---|---|
| `GET /api/alerts/inbox?limit=&status=&severity=` | any signed-in user | alerts with derived `status` and `assignee`; `limit` 1-200 (default 100) |
| `GET /api/alerts/{id}/events` | any signed-in user | incident timeline, oldest first |
| `PATCH /api/alerts/{id}` | operator | body: `status` (`open`/`acknowledged`/`resolved`), `assignee` (operator username, `null` clears), `note` (max 1000 chars); at least one |

Lifecycle: `open -> acknowledged`, `open -> resolved`, `acknowledged -> open|resolved`, `resolved -> open`.
Anything else is `409 invalid_transition` and changes nothing. A call that changes nothing (same assignee) returns 200,
writes no event and no audit row.

## Storage (migration `20261005000000`, additive)

`alerts.status`, `alerts.assignee`, `alerts.resolved_by`, `alerts.resolved_at` (all nullable) and the new table
`alert_events` (append-only timeline). Existing rows need no backfill: no `status` and `acknowledged = false` reads as
open, `acknowledged = true` reads as acknowledged, exactly as before. `POST /api/alerts/{id}/acknowledge` is unchanged.

## Audit

One atomic `alert_updated` row per change (`resource_type=alert`, details: target status, whether the assignee changed,
the assignee, whether a note was added and its length). The note text is not copied into the audit row.
Denied attempts are audited as `permission_denied` by `require_operator`, like every operator route.

## Frontend

Feature `alerts-centre`: route `/alerts` (nav group "Operate"), and a header widget (slot `header-actions`) that links to it,
shows the open-critical count as text, and raises a toast plus a live-region announcement for each critical alert that
appears after the first load. Sound is off by default; the choice is kept in `localStorage` under `twingrid.alerts.sound`.
