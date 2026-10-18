# Task 18 (twin parity roadmap): security and abuse review of the API

File name note: `docs/tasks/Task18_REPORT.md` already exists (an older, different Task 18); it is untouched.

Basis: the uploaded `TwinGrid-main__1_.zip` (read in full for `api/auth.py`, `api/startup_checks.py`, `api/config.py`,
`api/rate_limit.py`, `api/main.py`, `api/routes/*`, `api/middleware/body_limit.py`, `api/plugins/{admin_console,
login_lockout,client_errors,security}.py`, `api/services/webhook_*.py`, `src/log_redaction.py`, `src/admin_console/rules.py`,
`requirements.txt`, `requirements.lock`, `Dockerfile`, `Procfile`, `start.sh`). Evidence labels: **code** = read in the files;
**not run** = no pytest/fastapi/bcrypt in the sandbox, so none of the tests below were executed.

## Fixed (each has a test in `tests/test_task18_security_review.py`)
| ID | Sev | Finding (evidence: code) | Fix |
|---|---|---|---|
| T18-01 | Medium | `api/auth.py` never called `check_jwt_secret`; the placeholder / under-32-character rule ran only in the `python -m api.startup_checks` step of the Docker/Procfile/nixpacks CMD. `start.sh` sets `ENVIRONMENT=production` and runs uvicorn directly, so a weak secret booted. The existing `test_auth_delegates_the_secret_check` already expects delegation. | `SECRET_KEY = check_jwt_secret(read_secret(...))` |
| T18-02 | Low | `decode_token` accepted a validly signed token without `exp` (never expires) or `sub`. | `options={"require_exp": True, "require_sub": True}` |
| T18-03 | Low | `/auth/login` skipped bcrypt for an unknown username, so response time reveals which usernames exist. | `check_login_password`: one bcrypt verification (against a throwaway hash) either way |
| T18-04 | Low-Med | `webhook_service.deliver` logged the full webhook URL and `requests` exception text (which embeds the request path). Webhook paths are often the secret (chat incoming-webhook tokens); `src/log_redaction.py` only masks `?token=`-style query keys. | log `host [id]` and the exception class only |
| T18-05 | guard | no test proved every route is authenticated | `test_every_route_is_authenticated_or_explicitly_public` (explicit `PUBLIC_ROUTES` list) |

## Open risks (not fixed; no infrastructure added)
| Sev | Risk | Evidence | Suggested action |
|---|---|---|---|
| Medium | WebSocket JWT in the URL is accepted by default (`WS_ALLOW_QUERY_TOKEN` on); only uvicorn/websockets loggers are redacted, not a reverse proxy's access log | code: `websocket_routes.py`, `startup_checks.py` R13 | set `WS_ALLOW_QUERY_TOKEN=false` and `REDIS_URL` in production (ticket flow exists) |
| Low | `WS_ALLOWED_ORIGINS` unset = origin not enforced, and no startup rule requires it (token is not a cookie, so hijacking still needs a credential) | code | add a production rule or set it |
| Low | Rate limits and lockout are in-memory, per process; with `TRUST_PROXY_HEADERS` off behind a proxy all clients share one IP bucket on `/auth/login` | code, documented | set the proxy variables correctly; single worker |
| Low | Webhook SSRF guard has a DNS-rebinding window between validation and connect | code (documented in `webhook_security.py`) | connect to the pre-resolved IP if webhooks are exposed to untrusted operators |
| Low | `/docs`, `/redoc`, `/openapi.json` are public in production (the admin console links to them) | code: `api/main.py` | optional `ENABLE_API_DOCS` switch |
| Low | uvicorn buffers a WebSocket message up to its default 16 MiB before the app's 1 KiB check | code + uvicorn default (from memory) | `--ws-max-size 4096` in the start command |
| Low | Last-admin guard in `change_role` is count-then-write without a lock | code, not exercised | row lock or a DB constraint |
| Low | Shadow-mode summary reads the whole log file on every call | code | tail with `collections.deque(maxlen=limit)` |
| Low | No per-user cap on queued runs (only 30/min/user) | code: `run_service.py` | cap queued runs per user |
| Info | `requirements.txt` floors (`python-jose>=3.3`, `requests>=2.31`, `starlette>=0.37`) admit older releases; Docker installs the hash-pinned lock (python-jose 3.5.0, requests 2.34.2, starlette 1.7.0) and CI runs `pip-audit`, but `nixpacks.toml` installs from `requirements.txt`. CVE-to-version mapping is from memory: **unverified**, let `pip-audit` decide. | code | raise floors; consider PyJWT over python-jose |
| Info | bcrypt silently truncates passwords at 72 bytes; access tokens are not revoked at logout (15 min lifetime) | code | accepted |

## Checked, no action
No `shell=True`, `eval`, `pickle`, or unsafe `yaml.load` in `api/` or the served code paths; the only subprocess calls are fixed `git` argv lists. SQL is static `text()` or ORM. The ESG PDF uses a private temp file per request and deletes it. CORS is an explicit origin list (wildcard refused in production). Request bodies are capped at 1 MiB including chunked uploads. Admin routes sit behind `require_admin` with audited denials; audit CSV export is formula-safe; failed-login rows do not store the attempted username; refresh tokens are hashed, rotated, with reuse detection. The operator key and the client-error report key use `hmac.compare_digest`.

## Not run
All tests (sandbox lacks fastapi, python-jose, bcrypt, pytest). Whether `python-jose` accepts the `require_sub` option name is from memory: the T18-02 test will fail visibly if it does not.
