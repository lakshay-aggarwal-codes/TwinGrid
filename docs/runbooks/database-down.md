# Database down or failing writes

Signals: `/readyz` `checks.database` not `ok`; `telemetry_persist_failures_total` or `audit_write_failures_total` rising.

1. `docker compose ps db` and `docker compose logs db --tail 100` (disk full, crash, wrong password after a secret change).
2. `docker compose exec db pg_isready -U postgres`. Not ready: `docker compose restart db`; wait for the healthcheck.
3. The API reconnects on its own; confirm `/readyz` returns 200. Live telemetry written while the database was down was not
   stored (the failures are what the counter counts); nothing is replayed automatically.
4. Data loss or corruption suspected: stop writes, then follow `docs/OPERATIONS.md` (backup and restore drill).
