# Task 13 plan (AUTH-E)

Files: `api/plugins/demo_session.py` (new), `api/demo_guard.py` (new), `api/auth.py` (append `is_demo_claims`, `get_token_claims`), `api/routes/run_routes.py` (one dependency), `tests/api/test_demo_session.py`, `tests/authz_matrix.d/T13.yaml`, `docs/env/T13.md`, `.env.example` (append). `scripts/demo_seed.py` already seeds `demo_viewer`: unchanged.
Design: endpoint per section 8.3; the token is minted inside the plugin (no change to `create_access_token`); the read-only guard is a pure ASGI middleware installed by the plugin's `setup`, so every write route is covered without editing files this task does not own, plus an explicit `require_not_demo` dependency on `POST /api/runs`.
Verify: `pytest tests/api/test_demo_session.py tests/test_authz_matrix.py tests/test_auth_security.py tests/api/test_routes_auth_refresh.py -rs`.
