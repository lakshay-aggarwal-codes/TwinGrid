# Task 9 — AUTH-A Access-request backend          Status: PARTIAL
Base: TwinGrid-main.zip (no git history; local baseline tag; owner's working copy not seen)   Date: 2026-10-20
Environment: Python 3.12.3 (repo pins 3.12.10), pytest 9.1.1, ruff 0.6.9, FastAPI 0.150.0 (lock 0.141.1), SQLAlchemy 2.0.55,
aiosqlite 0.22.1, alembic 1.20.0. No PostgreSQL, no TensorFlow/torch, no Node, no SMTP.

## Summary
Contract §8.1 is implemented end to end on the backend: table + migration `20261101000000` (single head, partial unique index),
token/ref/decoy helpers, a transactional idempotent state machine, 4 public and 6 admin routes, audit rows, matrix fragment and docs.
54 new tests pass. PARTIAL only because PostgreSQL could not be exercised, `tests/test_authz_matrix.py` (Task 3) does not exist in this
tree so the T9 fragment is unconsumed, and the real mail adapter (Task 10) is absent (the hook was tested with doubles).

## Acceptance checklist
- All contract §8.1 behaviours -> MET on SQLite (see test names in `tests/api/test_access_requests.py`): 202 same-shape submission for new,
  duplicate-pending (token rotates) and decoy cases; generic 422; identical 404 for unknown ref/wrong token; resend always 202; single
  400 body for every bad activation token; password policy; no session on activation; admin list/detail/approve/reject/resend with
  403 + audited denial; approve idempotent, crossed transitions 409; limits 5/h+3/24h, 60/min, 3/h, 10/h.
- One Alembic head -> MET: `alembic heads` = `20261101000000 (head)`; upgrade, downgrade -1, upgrade, `alembic check` clean on SQLite.
- ruff clean -> MET (`ruff check .`, `ruff format --check .`, 395 files).
- No secrets in logs -> MET for the tested flows (caplog at DEBUG: no raw token or password; the app's own logs carry no stored hash).
- Migration on PostgreSQL -> NOT RUN.

## Changed files
- CREATE `alembic/versions/20261101000000_access_requests.py` — table, indexes, partial unique `uq_access_one_pending` (sqlite_where + postgresql_where).
- MODIFY `models/db_models.py` — appended `AccessRequest` and status constants (marked T9 BEGIN/END).
- CREATE `src/access/{__init__,rules,tokens,service}.py`, `api/plugins/access_requests.py`.
- CREATE `tests/api/test_access_requests.py`, `tests/authz_matrix.d/T9.yaml`, `docs/env/T9.md`, this report and the plan.
- MODIFY `.env.example` — appended T9 block.
- MODIFY (not owned, forced by the new head) `tests/test_alembic_chain.py` (M10 pins) and `tests/test_task28_migration.py` (head pin).

## Commands run
- `pytest tests/api/test_access_requests.py` -> 54 passed.
- `pytest tests/api tests/test_alembic_chain.py tests/test_startup_checks.py tests/test_task28_migration.py`: baseline 29 failed / 716 passed / 1 skipped;
  after: 30 failed / 769 passed / 1 skipped, the single extra failure being the `test_task28_migration` head pin, which I then fixed
  (that file alone: 5 passed). The other 29 are the same tests as on baseline.
- `pytest tests/test_audit_service.py tests/test_task1_plugins.py tests/test_time_contract.py tests/test_truth_copy.py tests/test_task33_claims.py
  tests/test_task22_register_consistency.py tests/test_task7_observability.py tests/test_requirements_split.py tests/test_task11_data_truth.py
  tests/test_task20_docs_consistency.py tests/test_startup_checks.py`: 6 failed / 244 passed / 1 skipped before and after (same 6).
- `alembic upgrade head; alembic heads; alembic check; alembic downgrade -1; alembic upgrade head` on a throw-away SQLite file: all OK.
- `ruff check .` pass; `ruff format --check .` 395 files already formatted.

## Pre-existing failures observed (identical on baseline; causes not investigated)
29 in `tests/api`: `test_error_contract` (14), `test_provenance_writers` (5), `test_routes_optimize_esg_shadow` (3), `test_physics_v1_api` (2),
`test_task15_whatif_sensitivity` (1), `test_task27_carbon_schedule_route` (1), `test_routes_health_metrics::test_healthz_returns_503_when_db_down`,
`test_state_preview_isolation` (1), `test_task29_admin_console::test_create_refuses_duplicates_unsafe_urls_and_overflow`. 6 in the second set above.
Also a pytest quirk: listing `tests/api/...` files, then a root-level test file, then more `tests/api/...` files in ONE command makes the later
api tests error with "fixture 'client' not found" (79 errors, reproduced on baseline). Run api and root test files in separate commands.

## Not run / blocked
- `tests/test_authz_matrix.py` — does not exist yet (Task 3). Run after Task 3: `py -3.12 -m pytest tests/test_authz_matrix.py -v`.
- PostgreSQL 16: `alembic upgrade head; alembic check` against `postgresql+asyncpg://...` and a real concurrent-submission race
  (the unique-index race and the compare-and-set loss are tested with doubles on SQLite).
- Real mail (Task 10), frontend (Tasks 11/12), timing-equality of real vs decoy responses (not measured).

## Decisions and defaults used
- Only `pending` requests expire; an `approved` request stays approved until activated (its link has its own 24 h TTL and can be re-issued).
- Decoy: stateless. `ref` = masked UTC-day index + HMAC(email, day) (same ref per address per day, like a real duplicate); token = nonce || HMAC(nonce, ref),
  fresh each call; it polls `pending` until day-start + TTL, then `expired`, and is recognised for 30 days after that, then 404.
- Public bodies use `{"error": ...}` exactly as in the contract (not problem+json); admin errors use the existing problem+json except 409 `invalid_transition`.
- Audit rows are written with `request=None` so the audit writer does not store the client IP; `access_request_activated` has no actor (a new
  account's username is the visitor's address) and carries `user_id` in details. Created/approved/rejected/expired/activated are atomic;
  activation_failed and notify_failed are best-effort. `EVENT_MODES` untouched.
- `notify_*` describe the most recent mail for the request. Mapping: ok -> `sent`; `not_configured`/`mail_unavailable`/`no_owner_email`/`no_base_url` -> `not_configured`; else `failed`.
- No SAVEPOINTs: on a unique-index race or a failed account insert the whole transaction is rolled back (on SQLite a savepoint test showed the
  rollback of a later failure did not undo earlier work; PostgreSQL behaviour was not tested).
- Admin list paging: `before_id` is the id of the last item of the previous page (ids are uuids, so the keyset is `(created_at, id)`).
- Plugin `setup` raises without `ACCESS_TOKEN_PEPPER` in production, so the loader skips the plugin (fail closed) — `startup_checks` is not mine.
- Rate limits use `rate_limit._hit` with their own scopes (adding scopes to `api/config.py` was out of ownership).

## Requested cross-task changes
- Task 3: runner must merge `tests/authz_matrix.d/T9.yaml`; admin id routes are `admin: 404` (sample id does not exist), the list is `2xx`.
- Task 10: `src/notify/mail.py` is called as `send_access_mail(kind, to, ctx)` for `owner_new_request` (to = `ACCESS_NOTIFY_OWNER_EMAIL`, read by T9),
  `activation` (`{name, activation_url}`) and `rejected` (`{name}`); a result needs `.ok` and `.code`.
- Task 21 / integrator: `docs/architecture/system.md` (14 -> 15 revisions, head `20261101000000`), `docs/api/*`, optional `startup_checks` rule for the pepper;
  the two test pins I moved (`test_alembic_chain.py`, `test_task28_migration.py`) must be kept by the integrator.
- Tasks 11/12: status 404 is the only "unknown" answer; `can_activate` is true only for an approved request with a live link; `decided_by` is a user id.

## New limitations or risks
- A duplicate pending submission rotates the status token (contract): anyone who knows an address can make the real visitor's token stop working.
- Rate limits are in-memory per process. Admin `resend-activation` is not audited (the contract lists no action name for it).
- Passwords up to 128 chars are accepted but the existing `hash_password` truncates to bcrypt's 72 bytes.
- Rotating `ACCESS_TOKEN_PEPPER` invalidates every outstanding token and the stored IP hashes stop matching.

## Next tasks unblocked
- 10 (mail adapter), 12 (admin queue UI), 11 (visitor UX), 13 (demo session, shares the matrix/guard), 22 (viewer workflow e2e).
