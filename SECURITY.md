# Security

TwinGrid is a **simulation-based** digital-twin platform. It handles accounts and operational-looking data, but the
data is simulated and no real facility is connected. This file states what is implemented and what is only
configured. "Configured" means the file exists in the repository; it does not mean the check has run or passes.

## Reporting a vulnerability

Contact: `<OWNER MUST FILL>` (email address, or enable GitHub private vulnerability reporting under
Settings > Code security and put its link here).

Please do not open a public issue for a security problem. There is no formal disclosure programme, no bug bounty and
no response-time commitment; this is a competition/portfolio project maintained by one owner.

## What is implemented in the code

- **Authentication:** JWT (HS256) access tokens, short-lived (`JWT_EXPIRE_MINUTES`, default 15), plus opaque refresh
  tokens stored only as SHA-256 hashes, rotated on every use and revocable (`/auth/refresh`, `/auth/logout`).
  `JWT_SECRET_KEY` is required; the app refuses to start without it (`api/auth.py`).
- **Roles:** `viewer` and `operator`. Registering an operator needs the `X-Admin-Key` header to match
  `OPERATOR_REGISTRATION_KEY`. Denied operator actions are written to the audit log.
- **Rate limiting:** `/auth/login` 10/minute and `/auth/register` 5/hour per IP; every HTTP route is in a `general`
  per-user/IP window; heavier routes have their own classes. In memory, per process. Full table: `docs/api/README.md`.
- **Login lockout and WebSocket tickets:** see `docs/env/Task6.md`.
- **Errors:** one `application/problem+json` shape; unhandled errors return a generic 500 with no traceback, path or SQL.
- **CORS:** explicit origin list (`CORS_ALLOWED_ORIGINS`), no wildcard. Production start-up checks
  (`api/startup_checks.py`) reject known placeholder secrets.
- **Observability endpoints:** `/healthz` and the probes are unauthenticated. `/metrics` needs a bearer `METRICS_TOKEN`
  when one is set and is refused in production without one; in development with no token it is open.
- **Frontend bundle:** a test (`bundleScan`) fails if demo credentials appear in the production bundle.

## What CI runs (read from `.github/workflows/ci.yml`)

| Check | Job | Notes |
|---|---|---|
| ruff lint and format | `lint` | |
| External-data register | `lint` | `scripts/check_register.py` |
| Python dependency audit | `audit` | `pip-audit --strict` on the hash-pinned `requirements.lock`, no suppressions |
| Frontend dependency audit | `frontend` | `npm audit --audit-level=high` |
| Type check | `types` | pyrefly error-count ratchet; **fails on purpose until `PYREFLY_ERROR_CEILING` is recorded** |
| Tests | `test`, `test-postgres`, `frontend` | no skipped tests allowed in `test` |
| Image checks | `docker` | digest-pinned base image, non-root user, `/healthz` |

This repository has no CI log attached, so whether these jobs currently pass is **NOT VERIFIED**. A local
`npm audit` earlier reported 2 critical and 6 high findings (`reports/industry/IG00_reality_baseline.md`); that was
before later dependency work and has not been re-measured here.

## Scanning configured (not claimed as passing)

| Item | File |
|---|---|
| Dependency update PRs (pip, npm, GitHub Actions, Docker; weekly, grouped) | `.github/dependabot.yml` |
| CodeQL static analysis (Python, JavaScript/TypeScript) | `.github/workflows/codeql.yml` |
| Secret scan with gitleaks and a documented placeholder allowlist | `.github/workflows/secret-scan.yml`, `.gitleaks.toml` |
| SBOM (SPDX) for the repository | `.github/workflows/sbom.yml` |
| SBOM and provenance for release images | `.github/workflows/release.yml` (never run on a real tag) |

Known gaps: GitHub Actions are pinned to major tags, not SHAs (`docs/governance/UNPINNED_ACTIONS.md`); branch
protection is documented but not applied (`docs/governance/BRANCH_PROTECTION.md`); `CODEOWNERS` is a placeholder;
there is no network-level restriction on `/healthz` or `/metrics`; no penetration test or independent audit has been done.
