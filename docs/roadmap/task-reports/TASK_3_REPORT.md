# Task 3 — QA-001 Authorization matrix harness          Status: PARTIAL (written and statically checked, NOT run)
Base: `TwinGrid-main.zip` as uploaded (+ Task 2 applied is not required)     Date: 2026-10-20
Environment: Linux sandbox, Python 3.12 + PyYAML only. fastapi, httpx, sqlalchemy and pytest are not installed and there is no network, so the new test has never been executed.

## Summary
A route x role authorization matrix: `tests/authz_matrix.py` (loader, route discovery, helpers), `tests/authz_matrix.d/core.yaml` (74 HTTP routes + `/ws/live`) and `tests/test_authz_matrix.py`. The test probes every route over HTTP as anonymous, viewer, operator and admin, and fails if the app serves a route the matrix does not declare (or the matrix declares a route that no longer exists). Expectations were derived by reading each route's guard in the source; the first real run is what confirms them.

## Acceptance checklist
| Criterion | Result | Evidence |
|---|---|---|
| Every route served is declared | written, not run | `test_every_served_route_is_declared_and_nothing_stale_is_declared`; my static AST listing of `api/` found 74 HTTP routes + 1 websocket, and `core.yaml` matches it exactly (checked by script) |
| Adding a route without declaring it fails | written, not run | `test_a_newly_added_route_is_flagged_until_it_is_declared` adds a real dummy route, rediscovers, expects it reported, removes it |
| Anonymous/viewer/operator/admin outcomes pinned per route | written, not run | `test_every_role_gets_the_declared_outcome` (one test per route, 4 roles each) |
| Fragments per task, duplicates rejected | met (loader run here) | loader exercised in the sandbox: 74 routes load; a duplicate and an invalid class are rejected with file/entry named |
| Write routes only open to anonymous if on the allow-list | written, not run | `test_only_documented_write_routes_are_open_to_anonymous_callers` |
| Viewer writes limited to an allow-list | written, not run | `test_a_viewer_can_only_write_where_the_allow_list_says` (allow-list: `POST /api/runs`, `POST /auth/ws-ticket`) |
| Websocket anonymous/bad token refused | written, not run | `test_websocket_refuses_anonymous_and_bad_tokens` (close code 4001, as in `tests/api/test_websocket.py`) |
| Demo column | deferred to Task 13 | loader accepts an optional `demo` key; a tripwire test fails if one is declared before the harness has a demo-token fixture |

## Changed files
- `tests/authz_matrix.py` — new: loader, `discover(app)`, `diff_routes`, `sample_path`, status-class rules, allow-lists.
- `tests/authz_matrix.d/core.yaml` — new: the core matrix.
- `tests/test_authz_matrix.py` — new: self-contained fixtures (in-memory SQLite, one user per role, rate limit off), probes, completeness and policy tests.
- `docs/roadmap/task-reports/TASK_3_REPORT.md` — this report.

## How it works (and the interpretation I chose)
- Routes are discovered by walking `app.routes` (including lazily included routers, via the helper `api.plugins._iter_routes`), not from `app.openapi()`, so a route with `include_in_schema=False` cannot hide. A separate test cross-checks that everything OpenAPI documents is discovered.
- Status class `2xx` means **access granted** (anything except 401/403/405), because a probe must not run business logic: write requests send the body `[]` (always 422, but only after authentication and role checks), path ids are made up, and two side-effecting handlers are stubbed (`shadow_mode_routes._ensure_optimizer`, `optimization_routes.get_status`). `public` is the same check with different intent; anonymous may only be `401` or `public`.
- Anonymous "no token" is expected to be exactly 401. That is correct for FastAPI >= 0.122 (lockfile pins 0.141.1) but not verified here. If your first run shows 403 for every anonymous cell, change the single constant `MISSING_CREDENTIALS_STATUS` in `tests/authz_matrix.py`.

## Findings worth a decision (no application code was changed)
1. **Admin is refused on every `require_operator` route.** `require_operator` checks the exact role `operator` (`User.is_operator()`), so an `admin` token gets 403 on `/api/optimize*`, `/api/webhooks`, alert acknowledge/PATCH, asset move/edge routes and `/api/shadow_mode/sample` (11 routes). The matrix pins this as current behaviour (`admin: "403"`). Meanwhile admin IS allowed on work orders and optimizer proposals (`can_write`, `can_propose`). If admin should be a superset of operator, that is a code change for a later task; the matrix row would then flip to `2xx`.
2. `POST /auth/logout` is reachable without a bearer token (the refresh token in the body is the credential). It is not in the playbook's public list; I added it to the allow-list with that reason.
3. `/metrics` is public in development when `METRICS_TOKEN` is unset and closed in production; the test removes the variable so the result does not depend on your shell.

## Commands run
- `python3 -m py_compile` on both Python files: OK.
- Loader exercised directly (74 routes; duplicate and bad-class rejection verified).
- Script cross-check of `core.yaml` against an AST extraction of every route decorator in `api/`: no missing or extra routes. (This is how a wrong path was caught: the client-errors router has an `/api` prefix, so the path is `/api/client-errors`.)

## Pre-existing failures observed
None observed (no tests were run).

## Not run / blocked
- `pytest tests/test_authz_matrix.py -q` — the whole HTTP matrix, completeness, dummy-route and websocket tests. Run it first; expect any mismatch to be reported per route with the role and the status actually returned.
- `ruff check tests/authz_matrix.py tests/test_authz_matrix.py` and `ruff format --check ...` — not run. Imports follow the repo's isort layout and lines are wrapped to 120, but formatting is unverified.
- Runtime of the matrix is unknown; it runs real handlers for allowed GET cells (state, simulate, benchmark, ...). If it is slow, tell me and I will add a lighter probe.

## Decisions and defaults used
- Fixtures are local to the test module (the `client`/`make_user` fixtures live in `tests/api/conftest.py`, which this file does not see).
- `POST /api/runs` is `viewer: 2xx` per the playbook decision, with a comment pointing at Task 13's demo-token guard.
- PyYAML is imported by existing tests (`test_task8_release.py`, `test_task10_governance.py`) but I did not find it in the lock files; I changed no dependency files.

## Requested cross-task changes
- Every later API task: add `tests/authz_matrix.d/T<n>.yaml` rows for new routes (the completeness test fails otherwise).
- Task 13: add a demo-token fixture, delete `test_the_demo_column_is_not_declared_before_the_harness_can_test_it`, and add `demo:` cells.
- Task 9: its public routes under `/api/access-requests` are already covered by the allow-list prefix.

## New limitations or risks
- The test imports `api.plugins._iter_routes` (private helper) to walk lazily included routers; if that function is renamed the harness fails loudly at import.
- Expectations come from reading code, not from a run; treat the first run as the verification.

## Next tasks unblocked
Tasks 9, 13 and every task that adds routes can now declare them.
