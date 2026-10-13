# Task 9 - API reference generation

## What changed
- `scripts/gen_api_reference.py`: imports `api.main` (sets `JWT_SECRET_KEY` to a placeholder only if unset, forces `ENVIRONMENT=development`; no lifespan, DB or network), writes deterministic `docs/api/openapi.json` (FastAPI's own `app.openapi()`, sorted keys, LF) and `docs/api/README.md` (auth, rate-limit classes from `api.config`, error shape, endpoint table with role and rate class read from the live route dependencies). `--check` exits 1 if stale.
- `tests/test_task9_api_reference.py`: regenerates in memory and fails if either committed file is missing or stale; also checks determinism, no secret in output, every operation listed, pointer doc.
- `API_DOCUMENTATION.md`: now a short pointer (the old hand-written tables had drifted from the code).

## Assumptions
- Rate class per route = `general` (api/main.py applies it to every HTTP router) plus any scope found via `http_limit_scope`; `/auth/*` per-IP slowapi limits are read best-effort from the limiter and omitted if unavailable.
- The WebSocket `/ws/live` is not in OpenAPI; it is described by hand in the README text.
- No new env vars, so no `docs/env/Task9.md`.

## Test results
- Syntax of both new Python files checked (`ast.parse`: ok). Nothing else could be run, see below.

## Not verified
- The sandbox has no network and no FastAPI/pytest/ruff installed, so the generator and test have NOT been executed, and `docs/api/openapi.json` / `docs/api/README.md` could not be produced (I will not hand-write them: they must come from the real app).
- **One required command** for the staleness test to pass the first time: `python scripts/gen_api_reference.py`, then commit `docs/api/`.
