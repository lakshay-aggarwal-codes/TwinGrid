# Task 13 — AUTH-E Demo-session backend + demo read-only guard          Status: PARTIAL
Base: uploaded `TwinGrid-main.zip` (owner's `git status` not seen; Tasks 1 to 12 not assumed applied)     Date: 2026-10-20     Environment: Python 3.12.3 with no project dependencies (no fastapi, jose, pytest, ruff) and no network. Nothing could be run.

## Summary
`POST /auth/demo-session`, the read-only guard, the env docs, the matrix fragment and a 40-odd-case test module are written. Files compile (`py_compile`) and parse, and that is all that was checked: **no test has been run**.

## Acceptance checklist
| Criterion | Status |
|---|---|
| Disabled / unset -> 404 identical to an unknown route | written, unrun (`ApiError(404, "not_found", "Not Found")`; test compares both bodies minus `instance` / `request_id`) |
| Enabled -> `demo:true` viewer token, 30 min | written, unrun |
| No refresh token in response or table | written, unrun |
| Missing account -> 503 `demo_unavailable` | written, unrun |
| 20/hour/IP | written, unrun (test sets `2/hour` and a fixed IP) |
| Audit `demo_session_issued` | written, unrun |
| Demo token 403 on every write route (parametrised) | written, unrun: parametrised over every POST/PUT/PATCH/DELETE in `app.openapi()` except the allowed few |
| Demo token cannot reach `/api/admin/*` | written, unrun (relies on the existing `require_admin`) |
| `/auth/refresh`, `/auth/logout` sensible | written, unrun: refresh answers 401 (no token exists), logout 204 no-op; no code change |
| `bundleScan` unaffected | met by construction: no frontend file changed |

## Changed files
- `api/plugins/demo_session.py` (new): endpoint, settings, token mint, `setup(app)` installs the middleware.
- `api/demo_guard.py` (new): `require_not_demo`, `DemoReadOnlyMiddleware`, allow-list.
- `api/auth.py`: appended `is_demo_claims`, `get_token_claims` (block `T13`); nothing else touched.
- `api/routes/run_routes.py`: `Depends(require_not_demo)` on `POST /api/runs`.
- `tests/api/test_demo_session.py`, `tests/authz_matrix.d/T13.yaml`, `docs/env/T13.md`, `.env.example` (append block), plan and this report.

## Commands run
`python3 -m py_compile` on the new and changed Python files; `ast.parse`; a 120-column line check. No pytest, ruff or ruff format.

## Pre-existing failures observed
None (nothing ran).

## Not run / blocked
```
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock; pip install -r requirements-dev.txt
pytest tests/api/test_demo_session.py tests/api/test_routes_auth_refresh.py tests/test_auth_security.py -rs
pytest tests/test_authz_matrix.py -rs      # exists only if Task 3 was applied; it was not in the uploaded tree
ruff check .; ruff format --check .
```

## Decisions and defaults used
- **Error shape.** Section 8.3 shows `{"error": "..."}`; the repository has one error model (`api/errors.py`, problem+json) and the code lives in `type`: `urn:twingrid:error:not_found` / `demo_unavailable` / `demo_read_only`. I used the repository's model so a demo 404 really is identical to an unknown route. Task 11's client must read `type`, not `error`. If you want the literal `{error: ...}` body, say so; it needs a change in `api/errors.py`, which no task owns.
- **Guard by middleware, not per-route.** Task 13 may edit only `run_routes.py` among route files, yet must deny "every write route". A middleware installed from the plugin covers all of them, including routes added later. It only acts on a token whose signature and expiry verify and whose `demo` claim is the JSON boolean `true`.
- **Allowed writes for a demo token:** `/auth/ws-ticket`, `/auth/refresh`, `/auth/logout`, `/auth/login`, `/auth/demo-session`, `/client-errors`, `/api/client-errors`. The playbook names `/client-errors`; the real path is `/api/client-errors` (both listed).
- A `demo_viewer` whose role is not `viewer` is never issued a token (503): roles come from the DB on every request, so a promoted demo account would otherwise be a privileged public login.
- Compute-persisting routes found: only `POST /api/runs` (explicit dependency, also covered by the middleware). `POST /api/optimize*`, work orders, webhooks, proposals, admin writes are role-guarded already and also covered by the middleware.

## Requested cross-task changes
- Task 3: add the `demo` column to the matrix loader (`T13.yaml` carries it); until then `test_demo_session.py` enforces it.
- Task 11: read the error code from `type`.
- Task 21 / ops: set `TRUST_PROXY_HEADERS` correctly in deployment or all visitors share one 20/hour budget.

## New limitations or risks
- Unrun code: a failing import or fixture mismatch is possible (the tests use the `client`, `make_user`, `session_maker` fixtures of `tests/api/conftest.py`).
- The per-IP counter is in process memory (same mechanism as the other limits): it resets on restart and is per worker.
- Demo-denied writes are not audited (only issuance is).
- `get_current_user` still trusts the DB role for a demo token; the issuance check and the write guard are what keep it read-only.

## Next tasks unblocked
Task 11 (visitor UX) and Task 22 (viewer workflow) can call `POST /auth/demo-session`.
