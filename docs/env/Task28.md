# Task 28 environment variables

None added. The maintenance routes use existing rate-limit scopes, read on every request:

| Variable | Default | Used by |
|---|---|---|
| `RATE_LIMIT_TELEMETRY_READ` | `60/minute` | `GET /api/maintenance/health` |
| `RATE_LIMIT_ALERT_ACK` | `30/minute` | create, edit and status change of a work order |

The health thresholds (5 % / 20 % invalid samples, 10 % / 25 % of the valid range moved, 12 valid samples minimum) and the text limits (title 160, description 2000, note 500, assignee 64) are constants in `src/maintenance_health.py` and `src/work_orders.py`.
