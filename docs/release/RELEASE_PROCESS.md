# Release process

Status: **release pipeline configured**, not yet exercised by a real tag. Everything released is a simulation; release
notes and smoke-test results say "simulated" and make no claim about a real facility.

## Cutting a release
1. Move the `[Unreleased]` entries in `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD` (SemVer: breaking API/contract
   change = major, additive feature = minor, fix = patch). Merge to `main`; wait for CI green.
2. Tag the merge commit and push: `git tag vX.Y.Z && git push origin vX.Y.Z`. `.github/workflows/release.yml` runs only on
   `vX.Y.Z` tags, never on pull requests.
3. The workflow: **verify** (tag is SemVer, CHANGELOG section exists, commit is on `main`, CI passed for that commit) ->
   **image** (build, push to `ghcr.io/<owner>/<repo>-api:X.Y.Z` and `:X.Y`, OCI labels, SBOM and max-mode provenance
   attached by buildx, GitHub build-provenance attestation pushed to the registry) and **frontend** (`npm ci`,
   `npm run build`, `twingrid-frontend-X.Y.Z.tar.gz` + `.sha256`) -> **github-release** (notes from the CHANGELOG,
   frontend bundle attached).
4. Deploy (below), then run the smoke test.

## Environments
| Environment | Backend | Frontend | Database |
|---|---|---|---|
| Local | `docker compose up` | `npm run dev` | compose Postgres |
| Staging | not set up (see `DEPLOYMENT.md`) | | |
| Production | Railway (Nixpacks; same start command as the image) | static host, built from the release bundle | managed Postgres |

## Secret and variable names (values are never in the repo or in logs)
- Runtime (platform environment): `JWT_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `REDIS_PASSWORD`, `METRICS_TOKEN`,
  `OPERATOR_REGISTRATION_KEY`, `CORS_ALLOWED_ORIGINS`, `ENVIRONMENT`. Full list: `.env.example` and `docs/env/`.
- GitHub: `GITHUB_TOKEN` (automatic; `packages: write`, `id-token: write`, `attestations: write` on the image job only).
  Repository **variables** (not secret, inlined in the bundle): `RELEASE_VITE_API_BASE_URL` (required),
  `RELEASE_VITE_ERROR_REPORT_URL` (optional).
- Smoke test: `SMOKE_USERNAME`, `SMOKE_PASSWORD` (a viewer account made with `scripts/create_demo_user.py`).

## Deploy order
1. Database backup (`scripts/backup.py`) before any release containing a migration.
2. Backend: deploy the new image/commit. The start command runs `python -m api.startup_checks` (an unsafe production
   config exits non-zero before anything else), then `alembic upgrade head`, then uvicorn on `${PORT:-8000}`.
   Run migrations as a separate job instead by setting `RUN_MIGRATIONS=0` on the web service.
3. Worker (if used): same image, after the backend is healthy.
4. Frontend: publish the release bundle (its API URL is fixed at build time).
5. Smoke test: `SMOKE_USERNAME=... SMOKE_PASSWORD=... python scripts/smoke_test.py --base-url https://<api>`. Exit 0 =
   `/healthz`, `/readyz`, login, `/api/state`, one `/ws/live` frame (labelled simulated) and the history endpoint all
   answered. A fresh database has no history yet: an empty list passes; a 404 means the facility sensors are not seeded.

## Rollback
- Redeploy the previous image tag (or Railway's previous deployment). Images are immutable per tag.
- The frontend rolls back by publishing the previous release's bundle.
- **The schema is not downgraded.** Migrations are additive only (new tables or nullable columns; exactly one Alembic
  head, checked by `audit_alembic_graph.py`), so the previous application version runs on the newer schema. Never run
  `alembic downgrade` on production to undo a release; fix forward with a new additive migration.

## Migration-on-deploy safety
- Additive-only migrations (above) are what make a rolling or rolled-back deploy safe.
- Only one instance should migrate: with more than one backend instance, set `RUN_MIGRATIONS=0` on all and run
  `alembic upgrade head` once as a release step before the rollout.
- If startup fails on a migration, the process exits and the platform keeps the previous deployment serving; see
  `docs/runbooks/migration-failure.md`.

## Third-party actions
`actions/*` and `docker/*` actions are referenced by **major version tag, not commit SHA**: the sandbox that wrote the
workflow had no network and could not resolve SHAs. Pin before the first real release (resolve each tag to its commit
SHA and keep the tag as a comment): `docker/setup-buildx-action@v3`, `docker/login-action@v3`,
`docker/metadata-action@v5`, `docker/build-push-action@v6`, `actions/attest-build-provenance@v2`, plus GitHub-owned
`actions/checkout@v4`, `actions/setup-node@v4`, `actions/upload-artifact@v4`, `actions/download-artifact@v4`.

## Not verified
The workflow has never run on a real tag; the smoke test has been unit-tested against fakes only, not a live server.
