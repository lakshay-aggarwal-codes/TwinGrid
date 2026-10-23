# Task 29 environment variables

None added. The admin console reuses existing limiter scopes (no new settings):

| Routes | Scope | Variable (existing) |
|---|---|---|
| `GET /api/admin/*` (users, audit, export, webhook list and delivery log, system) | `telemetry_read` | `RATE_LIMIT_TELEMETRY_READ` |
| `POST /api/admin/users/{id}/role` | `alert_ack` | `RATE_LIMIT_ALERT_ACK` |
| `POST/PUT/DELETE /api/admin/webhooks...`, `POST .../test` | `webhook` | `RATE_LIMIT_WEBHOOK` |

Existing settings the console reports or depends on: `WEBHOOK_ON_SIMULATED` (shown on the Webhooks tab), `READYZ_CHECK_SCHEMA` and the other readiness settings (shown on the System tab, same answer as `/readyz`).

## Data file

`data/webhook_deliveries.json`: the most recent 200 webhook delivery attempts (real alert deliveries and admin test events). Records hold time, kind, webhook id (a fingerprint), host, delivered or not, HTTP status, an error kind and the duration. No URL path or query, no payload, no response body. `data/*.json` is already git-ignored. It is per process: with several API workers the log is partial.

## Roles

Admin accounts are not created through the console or sign-up. They come from the seed script or a direct database change (`users.role = 'admin'`). The console can promote and demote other users, never yourself. No migration, no new dependency.
