# Changelog

All notable changes to TwinGrid are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). TwinGrid is a **simulation-based**
digital twin: every figure it produces is simulated, and no entry below claims otherwise.

A release is cut by pushing a `vX.Y.Z` tag; the tag needs a `## [X.Y.Z] - YYYY-MM-DD` section in this file
(see `docs/release/RELEASE_PROCESS.md`). No version has been released yet.

## [Unreleased]

### Added
- Extension points: backend plugins (`api/plugins/`) and frontend feature modules (`src/features/`) (Task 1).
- Security headers, single-use WebSocket tickets (`POST /auth/ws-ticket`), login lockout (Task 6).
- Observability: client error reports, Grafana dashboard, optional Alertmanager profile, SLO and runbooks (Task 7).
- Release pipeline configured: tag-triggered `release.yml` (GHCR image with provenance and SBOM attestations,
  frontend bundle), `scripts/smoke_test.py`, `docs/release/RELEASE_PROCESS.md` (Task 8). Not yet exercised by a real tag.

### Changed
- `Procfile`, `nixpacks.toml` and the `Dockerfile` now share one start command: startup checks, then
  `alembic upgrade head` (skip with `RUN_MIGRATIONS=0`), then uvicorn on `${PORT:-8000}`. The Nixpacks/Procfile path
  previously ran neither the startup checks nor honoured `RUN_MIGRATIONS`; the Procfile `release:` phase was removed
  because the start command runs the migration.
