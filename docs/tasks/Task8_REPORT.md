# Task 8 — Release engineering and smoke test

Claim: **release pipeline configured** (never run on a real tag).

## What changed
- `.github/workflows/release.yml`: runs only on `vX.Y.Z` tags. `verify` (SemVer tag, CHANGELOG section, commit on `main`, CI green) -> `image` (GHCR, OCI labels, buildx SBOM + max provenance, GitHub provenance attestation) and `frontend` (bundle + sha256) -> `github-release`. Least-privilege permissions; only `GITHUB_TOKEN` is used; no push on PRs.
- `scripts/smoke_test.py --base-url`: `/healthz`, `/readyz`, login, `/api/state`, one `/ws/live` frame (ticket, falling back to token), history endpoint. Exit 0/1, 2 for usage errors. Credentials via `SMOKE_USERNAME`/`SMOKE_PASSWORD`; nothing secret is printed.
- `CHANGELOG.md` (Keep a Changelog, SemVer; `[Unreleased]` only, no invented versions), `docs/release/RELEASE_PROCESS.md`, `DEPLOYMENT.md` updated (also removed the stale `VITE_DEMO_*` build instruction).
- `Procfile`, `nixpacks.toml`, `Dockerfile` share one start command (startup checks, migration unless `RUN_MIGRATIONS=0`, uvicorn on `${PORT:-8000}`). Dockerfile unchanged (already that command).
- `tests/test_task8_release.py` (35 cases).

## Assumptions
- `nixpacks.toml` in the uploaded repo was already plain UTF-8 (ASCII); only its start command changed.
- **Behaviour change on the Nixpacks/Railway path:** it now runs `api.startup_checks` before starting, as the image already did. A production config the checks reject will fail the deploy instead of starting. Procfile `release:` removed (the start command migrates).
- Actions are pinned by major tag, not SHA (no network to resolve); all are listed in `RELEASE_PROCESS.md`.
- Release image name is `ghcr.io/<owner>/<repo>-api`; frontend needs repo variable `RELEASE_VITE_API_BASE_URL`.
- History check uses sensor `fac1.it_power_kw` (`--sensor` overrides); empty history passes, 404 fails.

## Test results (real output)
- pytest is not installed in the sandbox (no network), so the file was run with a minimal pytest shim: `passed 35 failed 0`. Mutation check (extra `release:` line in Procfile): `passed 34 failed 1`, the agreement test.
- Smoke script run against a local fake HTTP server: login/state/history/healthz passed, a 503 `/readyz` and the missing `websockets` module were reported as `[FAIL]`, exit 1 as designed.
- `release.yml` parses as YAML; `nixpacks.toml` parses as TOML.

## Not verified
- Real `pytest`/`ruff` run; the workflow on GitHub; a real WebSocket frame (`websockets` not installed here); the smoke test against a live deployment.
