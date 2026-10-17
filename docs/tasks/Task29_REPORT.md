# Task 29 — Admin console

**Claim:** an admin-only console for users and roles, the audit log (filters and export), webhooks (add, change, test, delivery log) and system status, with every write audited. A UX gate hides it from non-admins; the backend refuses every `/api/admin/*` route to a non-admin regardless.

## What changed
- **Backend** `api/plugins/admin_console.py` (+ pure rules in `src/admin_console/rules.py`):
  - Roles: only the exact role `admin`. Non-admin, no token or unknown role: 403 on every route, best-effort `permission_denied` audit row. Roles are read from the database on every request, so a change applies at once.
  - Users: `GET /api/admin/users` (no password hashes); `POST /api/admin/users/{id}/role` (never on yourself, never removing the last admin, atomic `user_role_changed` row).
  - Audit: `GET /api/admin/audit` (filters: action, outcome, user, resource type, from, to; newest first, paged by `before_id`) and `GET /api/admin/audit/export` (CSV or JSON, newest 10,000 matching rows, `X-Export-Truncated`). CSV cells that look like formulas are prefixed with `'`. Each export is itself audited (`audit_exported`) before anything is returned. Read helpers were added to `api/services/audit_service.py` (still no update or delete).
  - Webhooks (existing file registry and `webhook_service`): list, add, change URL (`webhook_registry.replace`, atomic, same position), remove, send a clearly-labelled test event, delivery log. A webhook is shown only as an id (fingerprint), scheme, host and port. The path and query can hold secrets and are never returned, logged or audited.
  - Delivery log: `src/webhook_deliveries.py` (bounded file, newest 200). `webhook_service.deliver()` now returns a result (kind of failure, never text), `_post_one` records every real alert delivery, and `send_test` records tests. Redirects are refused.
  - System: `GET /api/admin/system`: readiness (calls the same `/readyz` code), migration head vs database revision, versions, uptime, model state and registry, API-docs paths. A part that cannot be read is reported as unavailable.
- **Frontend** `twin-stream-insight-main/src/features/admin-console/`: route `/admin`, nav item in an `Admin` group with `minRole: "admin"`, four tabs (only the open tab fetches). Errors are worded by kind, never from server text. A pasted webhook URL is never displayed again.
- Shared files touched: `tests/conftest.py` (autouse fixture keeps the delivery log out of `data/` during tests), `features/registry.test.ts` (`admin-console` added to the shipped list).

## Assumptions
- Admin accounts come from the seed script or a direct database change; the console cannot create users (no create, disable or delete).
- "Edit" a webhook means replacing its URL. Subscribers are identified by a 16-hex fingerprint of the URL.
- Uptime counts from when the API loaded its plugins. The delivery log is per process (partial with several workers).
- New audit actions (`user_role_changed`, `webhook_updated`, `webhook_test_fired`, `audit_exported`) are not added to `EVENT_MODES`, which a test pins. Existing limiter scopes are reused; no new variable.
- Inherited, not fixed: the SSRF check resolves DNS once and `requests` resolves again when it sends (the existing webhook limitation).

## Test results
- `tests/test_task29_admin_rules.py` (roles, filters, CSV injection, webhook identity and no-secret views, registry swap, delivery log, `deliver`/`send_test` with `requests` replaced), under a small pytest stand-in: `passed 48, failed 0`. Task 27's backend tests still pass (35, 1 skipped).
- Frontend `model.test.ts` (Node 22 + `expect` stand-in): `passed 16, failed 0`. A real React server render of all four panels (hooks, boundary and API stubbed) passed: roles, no select on your own row, hosts and last delivery in words, no secret-looking path, docs links, "NOT MEASURED" for unreadable parts. TypeScript syntax parse of every changed `.ts`/`.tsx`: 0 errors. `py_compile` clean on every changed Python file.
- Written, not executed: `tests/api/test_task29_admin_console.py` (permission matrix over all 11 routes for no token, viewer and operator; users, role changes, audit filters and paging, export and bound, webhook add/edit/test/delete and delivery log, system status), `schema.test.ts`, `AdminPage.test.tsx`, `registration.test.tsx`.

## Not verified
- `pytest`, `ruff check` and `ruff format --check` (the new Python test files are not ruff-formatted; run `ruff format`), `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build`, `bundleScan`: no installed toolchain and no network.
- The plugin and route were never imported or called (FastAPI, SQLAlchemy missing), so every HTTP behaviour above, including that a 403 leaves state untouched, rests on tests that have not run. Rate-limit behaviour for the reused scopes is untested here.
