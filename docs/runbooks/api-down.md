# API down

1. `curl.exe -s -o NUL -w "%{http_code}" http://localhost:8000/livez` (200 = process alive). No answer: continue.
2. `docker compose ps backend` then `docker compose logs backend --tail 100`. A start-up refusal prints rule names, never values
   (`python -m api.startup_checks`): fix the named variables (see `.env.example`), then `docker compose up -d backend`.
3. Container restarting in a loop: look for the migration step (see [migration-failure.md](migration-failure.md)) or a missing
   `JWT_SECRET_KEY` / `POSTGRES_PASSWORD` / `REDIS_PASSWORD` (compose refuses to start without them).
4. `/livez` answers but `/readyz` is 503: read `checks` in the body (`database`, `schema`, `broadcast`) and go to the matching runbook.
5. Recovered: confirm `up{job="twingrid-api"}` is 1 in Prometheus (if the overlay runs) and that the live feed resumes.
