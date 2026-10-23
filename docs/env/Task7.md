# Task 7 environment variables

All optional, read per call, defaults keep today's behaviour. `.env.example` is not changed (Task 32 appends this).

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `CLIENT_ERRORS_MAX_BYTES` | `8192` | `src/client_errors` | Largest accepted report body; clamped to 256..65536. Larger -> 413. |
| `CLIENT_ERRORS_RATE_LIMIT` | `20/minute` | same | Per client IP. Malformed -> default. Over the limit -> 429 with `Retry-After`. |
| `CLIENT_ERRORS_REPORT_KEY` | unset | same | Write-only ingest key (16+ characters), sent as `?key=` in `VITE_ERROR_REPORT_URL`. Unset: endpoint open in development/test, 404 in production. |
| `GRAFANA_ADMIN_PASSWORD` | none (required by the overlay) | observability overlay | Grafana admin password. |

Overlay: `docker compose -f docker-compose.yml -f deploy/observability/docker-compose.observability.yml --profile observability up -d`
(`--profile alerting` adds Alertmanager). Create `deploy/observability/secrets/metrics_token` containing the `METRICS_TOKEN` value first.
