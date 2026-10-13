# Rotating secrets (names only; never write a value into a ticket, chat or log)

| Secret | Effect and procedure |
|---|---|
| `JWT_SECRET_KEY` | Hard cutover: every access token and WebSocket session ends; the client refreshes. See `docs/security/KEY_ROTATION.md` (no `kid` support yet). |
| `METRICS_TOKEN` (or `_FILE`) | Read on every request: no restart. Update it, then the file mounted at `deploy/observability/secrets/metrics_token` for Prometheus. |
| `CLIENT_ERRORS_REPORT_KEY` | Change it on the API, then rebuild the frontend with the new `?key=` in `VITE_ERROR_REPORT_URL` (build-time). Old browsers get 401 until they reload. |
| `POSTGRES_PASSWORD` | Change it in Postgres first (`ALTER USER`), then in the environment, then restart `backend`, `worker`, `mqtt-ingest`. |
| `REDIS_PASSWORD` | Change in the environment and restart `redis`, `backend`, `worker`; WebSocket tickets in flight (30 s) are lost. |
| `GRAFANA_ADMIN_PASSWORD` | Change it in Grafana's UI as well; the environment value only seeds a new volume. |

A leaked secret: rotate first, then check logs for use (redaction hides the value, `request_id` and route remain).
