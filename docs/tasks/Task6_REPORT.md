# Task 6 report: security headers, WebSocket tickets, lockout

## Delivered
Security headers (API + `netlify.toml` CSP), single-use WebSocket tickets with frontend use and fallback, `ticket=`
redaction (backend + frontend), login lockout/backoff, probe/metrics exposure tests, startup rule R13, docs
(`docs/security/*`, `docs/env/Task6.md`, frontend RISKS R-1 updated).

## Files
New: `api/middleware/security_headers.py`, `api/plugins/{security,ws_tickets,login_lockout}.py`, `src/ws_tickets/__init__.py`,
`src/login_lockout.py`, `tests/test_task6_security.py`, docs above.
Modified: `api/routes/websocket_routes.py`, `api/startup_checks.py`, `netlify.toml`, `tests/test_startup_checks.py`
(R13 case, 2 MANAGED names), `twin-stream-insight-main/src/api/wsTransport.ts` (+test: two probe tests now count only
`/healthz` calls; 8 ticket tests added), `src/lib/errorReporter.ts` (+test), `docs/frontend/RISKS.md`.

## Verified
- `tests/test_task6_security.py`: 59 passed alone and inside a 638-test combined run.
- Combined run (tests/api, plugins, security, auth, startup, ws): 26 failures, **identical set to the untouched repo** (FastAPI 0.143 route table, `.env.example` gaps, auth reload).
- `ruff check` and `ruff format --check` clean on changed Python.
- Frontend: eslint clean on changed files; full vitest 1003 passed, 14 files fail to import because `src/runs/*` is absent from the upload (pre-existing); `tsc` errors are only those missing `runs` modules.

## Not verified
Full backend suite (TensorFlow/torch not installed), real Redis, Postgres, a browser (CSP allowances), `vite build`
(blocked by the missing `src/runs`), Netlify actually serving the headers.

## Design decisions / risks
`?token=` stays enabled by default so the live feed cannot break; lockout is process-local and keyed by (IP, username)
to avoid letting an attacker lock a victim; plugins wrap the finished middleware stack so headers cover 413/500.
Task 32 must add the new env vars to `.env.example`.
