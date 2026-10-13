# Runbooks

Start here: find the symptom, open the runbook. All commands are Windows PowerShell from the repo root and assume the
default stack (`docker compose`; add `-f docker-compose.yml -f docker-compose.demo.yml --env-file .env.demo` for the demo).

| Symptom or alert | Runbook |
|---|---|
| `ApiDown`, the site does not load, `/livez` fails | [api-down.md](api-down.md) |
| `/readyz` says `database` is not ok; `TelemetryPersistFailures`, `AuditWriteFailures` | [database-down.md](database-down.md) |
| `LiveFeedStale`, `BackgroundLoopRestarting`, `WebSocketFramesDropped`, `/readyz` says `broadcast` is not ok | [stale-feed.md](stale-feed.md) |
| API will not start after a deploy, `/readyz` says `schema` is `behind` or `missing` | [migration-failure.md](migration-failure.md) |
| `HighServerErrorRatio`, `SlowRequestsP95` | [high-5xx.md](high-5xx.md) |
| `AnomalyScoringErrors`, a model shows `degraded` or `not_loaded` in `/readyz` | [artifact-load-failure.md](artifact-load-failure.md) |
| A secret leaked or must change | [rotating-secrets.md](rotating-secrets.md) |

How to find one request in the logs: every response carries `X-Request-ID`; every log line is one JSON object with the
same `request_id` (HTTP, WebSocket and queued jobs started by that request). Example:
`docker compose logs backend --no-log-prefix | Select-String '"request_id": "<id>"'`.
Secrets (tokens, tickets, passwords, bearer values) are redacted from these lines. Probes: `/livez` (process), `/readyz`
(can serve; statuses only, no detail), `/metrics` (needs `METRICS_TOKEN` in production).
