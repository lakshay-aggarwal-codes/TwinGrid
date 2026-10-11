# Security

## Authentication

JWT (HS256), issued via `/auth/login`. `JWT_SECRET_KEY` is **required** — the app refuses to start without it (Phase 12; previously fell back to a hardcoded placeholder, which was a real vulnerability if anyone forgot to set the env var).

## Rate limiting

- `/auth/login`: 10/minute/IP
- `/auth/register`: 5/hour/IP
- `/api/optimize`: 10/minute/IP (can trigger expensive RL training)

## CORS

Scoped to an explicit origin list (`CORS_ALLOWED_ORIGINS` env var), not a wildcard — see `api/config.py`.

## Known simplifications (stated plainly, not hidden)

- `/healthz` is unauthenticated. `/metrics` requires a bearer `METRICS_TOKEN` when one is configured and is refused in production without one (`api/routes/metrics_routes.py`); in development with no token configured it is open. This deployment has no network-level restriction on either endpoint (no private network/VPC).
- CI runs `pip-audit` (strict, on `requirements.lock`) and `npm audit --audit-level=high` (`.github/workflows/ci.yml`, jobs `audit` and `frontend`). Dependabot is not configured. Whether those jobs pass is NOT VERIFIED (no CI log attached); a local `npm audit` reports 2 critical and 6 high findings (`reports/industry/IG00_reality_baseline.md`).

## Reporting

This is a student/portfolio project without a formal disclosure process. Open an issue or contact the maintainer directly.
