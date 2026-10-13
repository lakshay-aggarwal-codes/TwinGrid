# Task 7: observability

## What changed
- **Logs:** the JSON logger already put `request_id` on every line and in `X-Request-ID` (6-character minimum kept). Added: secret redaction in the JSON logger (`src/log_redaction.py`, applied to message and exception text in `api/logging_config.py`): passwords, tokens, `ticket=`, refresh tokens, `Authorization`/Bearer values, JWT-shaped strings. WebSocket handlers already run inside `RequestIDMiddleware` (now tested). Queued jobs: `task_queue.enqueue` attaches the request id as `job.meta`, and `run_whatif_job` / `train_optimizer_job` are wrapped by `src/log_context.with_request_id` (restores the id, logs start/finish/fail with it).
- **`POST /api/client-errors`** (`api/plugins/client_errors.py`, logic in `src/client_errors.py`): accepts exactly the `errorReporter.ts` payload; cap `CLIENT_ERRORS_MAX_BYTES` 8192 (enforced while streaming), `CLIENT_ERRORS_RATE_LIMIT` 20/minute per IP, redacted, one log line; `client_errors_received_total{outcome}` with outcomes accepted, disabled, rate_limited, unauthorised, too_large, invalid. The server access log is also redacted (`?key=`).
- **Metrics:** `telemetry_persist_failures_total` and `telemetry_retention_deleted_rows_total` reused unchanged (a test pins the names).
- **Overlay** `deploy/observability/` (Prometheus, Grafana, optional Alertmanager, 10 alert rules, 12-panel dashboard), opt-in via `--profile observability` / `alerting`; default stack untouched.
- **Docs:** `docs/runbooks/` (7 runbooks + index), `docs/SLO.md` (all targets NOT MEASURED), `docs/env/Task7.md`.
- Touched existing files: `api/logging_config.py`, `src/task_queue.py`, `src/task_jobs.py`, `src/run_jobs.py` (small additive edits).

## Assumptions
1. **Auth for the endpoint.** The reporter uses `sendBeacon` with `text/plain`, so it cannot send any header or token. The endpoint is token-bound: `?key=<CLIENT_ERRORS_REPORT_KEY>` in `VITE_ERROR_REPORT_URL`, or alternatively a valid bearer token. The key is visible in the frontend bundle (a write-only ingest key, like a Sentry DSN). No key: open in development/test, 404 in production.
2. Alerts exist only for metrics the API exports. Migration failure and artifact load failure have no metric, so they are runbook-only.
3. Metrics stay process-local; the overlay scrapes one API instance.

## Test results
- Run here (stand-in runner, real pytest is not installed): `tests/test_task7_redaction.py` 64 passed, 0 failed.
- NOT RUN: `tests/test_task7_observability.py` and the rest of `pytest`, `ruff`, all frontend checks. No network or dependencies in this sandbox; the files only passed `py_compile`.

## Not verified
- App-level tests (HTTP, WebSocket, job propagation, overlay file checks) and `ruff` import ordering.
- Compose overlay, Prometheus rules, Grafana dashboard against a running stack. Claim: "alerts configured", not "alerts verified".
