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
- `/api/whatif` (and its preset scenarios) now return `physics_version` and a `provenance` object: origin, scenario kind,
  weather source, plant, control, model version, registry version and API version (R3 Task 2).
- CI: a `gate` job that requires `lint`, `types`, `test`, `test-postgres`, `audit`, `frontend` and `docker`;
  `scripts/npm-audit-gate.mjs`, which fails on any high or critical npm advisory that is not waived in
  `docs/frontend/waivers/npm_audit.md`; contract fixtures re-captured from the running backend, including new `assets.json`
  and `facility.json` (R3 Task 11).
- Carbon: an importer for Ember's India monthly data (`scripts/make_carbon_from_ember_india.py`). The level is real but the
  same for every hour, and the provider now labels a flat curve as having no time-of-day shape (`R_CARBON_REPORT.md`).
- A new stored baselines run, `baselines-v6`, recorded on the current lock and configs. `baselines-v5` is left unedited and
  superseded (R3 Task 4).

### Changed
- `Procfile`, `nixpacks.toml` and the `Dockerfile` now share one start command: startup checks, then
  `alembic upgrade head` (skip with `RUN_MIGRATIONS=0`), then uvicorn on `${PORT:-8000}`. The Nixpacks/Procfile path
  previously ran neither the startup checks nor honoured `RUN_MIGRATIONS`; the Procfile `release:` phase was removed
  because the start command runs the migration.
- `/api/whatif` and `/api/whatif/sensitivity` accept the chilled-water set-point range of the active physics version:
  5 to 15 C under `legacy-0`, 16 to 25 C under physics `1`. The query allows 5 to 25 C and the route then checks the value
  against the active version, so the What-if Lab's 16 to 25 C requests no longer get a 422 (R3 Task 1).
- The pyrefly error ceiling is 944 on Linux CI, the count measured after the `types` job began installing the dev
  requirements. The earlier 1120 did not reproduce (main counted 1123, then 1125); see `reports/postT9/T11_ci_run.md`.

### Fixed
- The public demo session may call `POST /api/copilot/ask` (no write was found on that route); the copilot reads the newest
  signal sample whose quality is `ok`; an alert id made of non-ASCII digits gets a 404, not a 500; a future-dated reading is
  `unknown` with reason `future`, never `normal` (R3 Tasks 5 to 8; evidence in `R3_TASKS_5_TO_10_EVIDENCE.md`).
- The authorization matrix collects and enforces the `T13.yaml` overlay (R3 Task 9).
- The test for a non-ASCII `X-Request-ID` sends the header as bytes and runs on every platform instead of skipping.

### Security
- Recorded waivers: `ecdsa` PYSEC-2026-1325 and `python-jose` PYSEC-2026-4298 (`docs/security/waivers.md`), and `zod`
  GHSA-mrhx-c7xc-m3w5 (`docs/frontend/waivers/npm_audit.md`). Neither list names a patched release. Each expires and must be
  re-checked before then.
- The gitleaks allowlist names the e2e stack's placeholder `ACCESS_TOKEN_PEPPER` (`e2e-test-pepper-...`), which is not a secret.
