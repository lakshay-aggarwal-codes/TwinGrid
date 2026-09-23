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

- `/metrics` and `/healthz` are unauthenticated — standard practice for infrastructure endpoints, but this deployment has no network-level restriction on them either (no private network/VPC). Acceptable at this scale; would need addressing for a genuinely production-grade multi-tenant deployment.
- No dependency vulnerability scanning is currently automated in CI (a reasonable Phase 15 follow-up: `pip-audit` or GitHub's Dependabot).

## Reporting

This is a student/portfolio project without a formal disclosure process. Open an issue or contact the maintainer directly.