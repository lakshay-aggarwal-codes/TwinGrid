# Deployment

## Two independent deployment paths — read this first

This project has **two separate build/deploy paths that do not affect each other**:

1. **Railway (production, live today)** — builds via **Nixpacks** (`nixpacks.toml`, `Procfile`), *not* the Dockerfile. This is what actually serves `https://function-bun-production-6ce5.up.railway.app`.
2. **Docker / `docker-compose`** (Phase 14) — used for local development (`docker-compose up`) and CI's build-verification step (Phase 15). Not currently used by Railway.

Editing the Dockerfile does **not** change the live Railway deployment, and editing `nixpacks.toml`/`Procfile` does **not** change local Docker behavior. If you ever want Railway to build from the Dockerfile instead, that's a real migration (Railway supports it via a `railway.json` with `"builder": "DOCKERFILE"`) — it needs its own validation pass (the Dockerfile currently hardcodes port 8000; Railway injects a dynamic `$PORT` that Nixpacks already respects correctly), not a silent switch.

## Environments

| Environment | Backend | Frontend | Database | Notes |
|---|---|---|---|---|
| **Local dev** | `docker-compose up` (Phase 14) or `uvicorn api.main:app --reload` | `npm run dev` in `twin-stream-insight-main/` | Local Postgres (compose) or SQLite-free local Postgres install | Use `.env` copied from `.env.example` |
| **Production** | Railway (Nixpacks) | Vercel/Lovable | Railway-managed Postgres | Live URLs in the patent PDF |
| **Staging (recommended, not yet set up)** | Railway — create a second Railway *environment* in the same project, fed from a `staging` branch | Vercel preview deployments (automatic per-branch, free) | Separate Railway Postgres instance | See "Adding staging" below |

## Required environment variables (consolidated from every phase)

| Variable | Introduced in | Required? | Notes |
|---|---|---|---|
| `JWT_SECRET_KEY` | Phase 12 | **Yes — app refuses to start without it** | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_EXPIRE_MINUTES` | Phase 12 | No (default 60) | |
| `DATABASE_URL` | Original | Yes | Railway auto-injects this for its managed Postgres add-on |
| `CORS_ALLOWED_ORIGINS` | Phase 12 | No (defaults to the known Lovable frontend URL) | Comma-separated if multiple |
| `NSRDB_API_KEY`, `NSRDB_EMAIL` | Phase 2 | Only if running `src.ingestion.solar_nsrdb` | Free signup, not needed for the API itself to run |
| `ELECTRICITYMAPS_API_KEY`, `ELECTRICITYMAPS_ZONE` | Phase 2 | Only if re-running carbon ingestion | Not needed for the API itself to run — `data/cleaned/carbon_intensity.csv` is already generated and used by `src/carbon_provider.py` |
| `FACILITY_LATITUDE`, `FACILITY_LONGITUDE`, `FACILITY_TIMEZONE` | Phase 2 | Only for NSRDB ingestion | |
| `VITE_DEMO_USERNAME`, `VITE_DEMO_PASSWORD` | Phase 3 | Yes, frontend only | Set in Vercel/Lovable's environment variable settings, not just locally — must match an account created by `scripts/create_demo_user.py` |

## Deploying the backend (Railway, current production path)

1. Push to the branch Railway is watching (currently the default branch) — Railway auto-builds via Nixpacks.
2. Set the required env vars above in Railway's dashboard (Variables tab), not in code.
3. Railway's managed Postgres add-on provides `DATABASE_URL` automatically if attached.
4. After first deploy (or after any user/auth changes), run once: `python scripts/create_demo_user.py --base-url <railway-url> --password <real-password>` to (re)create the frontend's demo viewer account.

## Deploying the frontend (Vercel/Lovable)

1. Set `VITE_DEMO_USERNAME`/`VITE_DEMO_PASSWORD` in the platform's environment variable settings (build-time, per Vite convention).
2. Redeploy — Vercel/Lovable auto-builds on push, same as Railway.

## Health checks

- `GET /healthz` (Phase 14) — unauthenticated, checks DB reachability, returns 503 on failure. Use this for any external uptime monitor (e.g., UptimeRobot's free tier) pointed at the Railway URL.
- `GET /api/health` — authenticated, for clients confirming reachability with a valid session.

## Logs

- Railway's built-in log viewer shows stdout, which is now structured JSON per request (Phase 16), including `request_id` — searchable/filterable by that ID if you need to trace one specific request a user reports an issue about.
- Local: `docker-compose logs -f backend`.

## Monitoring — current real limits, stated plainly

`GET /metrics` (Phase 16) exists and returns valid Prometheus text format, but **nothing is currently scraping it** — Railway doesn't run a Prometheus server, and none is deployed here. Today, `/metrics` is only useful via a manual `curl` check or if you set up a free external service (e.g., Grafana Cloud's free tier can scrape a public HTTP endpoint on an interval) to pull from it. Don't claim "monitoring" is fully wired end-to-end — the metrics *exist and are correct*, but nothing is *watching* them yet. That's a reasonable next step, not something this phase pretends is already done.

## Rollback strategy

Railway keeps previous deploys and supports one-click rollback from its dashboard (Deployments tab → select a previous successful deploy → "Redeploy"). No custom rollback tooling needed at this scale — Railway's built-in mechanism is sufficient and simpler than building a parallel one.

## Adding a staging environment (recommended, not yet done)

1. In Railway's project settings, create a second **environment** (Railway's term, separate from a "service") named `staging`, pointed at a `staging` git branch.
2. Attach a separate Postgres instance to it (Railway environments don't share databases by default).
3. Set a **different** `JWT_SECRET_KEY` and a **different** demo viewer account for staging — never reuse production secrets in staging.
4. Vercel/Lovable already gives you this for free on the frontend side via preview deployments per branch/PR — no extra setup needed there.