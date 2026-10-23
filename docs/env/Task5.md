# Task 5: demo data and one-command demo: environment

Nothing here is read by the API. These variables belong to the demo tooling only; `.env.example` is unchanged.

| Variable | Read by | Default | Meaning |
|---|---|---|---|
| `DEMO_MODE` | `scripts/demo_seed.py` (and set by `docker-compose.demo.yml`) | unset | The seed refuses to run (exit code 2, no database access) unless this is exactly `true` (case-insensitive). |
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `JWT_SECRET_KEY` | `docker-compose.yml` | none | `scripts/demo.ps1` / `demo.sh` generate random values on first run into `.env.demo` (git-ignored by `.env.*`) and reuse them afterwards. Infrastructure secrets only; the demo user passwords are never written there. |

`docker-compose.demo.yml` sets `ENVIRONMENT=development` on the API for the demo (the base default, `production`, requires a `METRICS_TOKEN` and explicit CORS origins). Do not use the overlay for a real deployment.
