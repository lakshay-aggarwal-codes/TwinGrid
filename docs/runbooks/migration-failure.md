# Migration failure

The API image runs `alembic upgrade head` on start (set `RUN_MIGRATIONS=0` to run it as a separate job).

1. `docker compose logs backend --tail 100` for the failing revision. `python audit_alembic_graph.py` must report one head.
2. `docker compose exec db psql -U postgres -d digital_twin -c "select * from alembic_version;"` shows where the database is.
3. Migrations here are additive (new tables or nullable columns): fix the cause and re-run `docker compose up -d backend`.
   A half-applied revision on Postgres rolls back with its transaction.
4. Do not edit `alembic_version` by hand. If a deploy must be undone, restore the pre-deploy backup (`docs/OPERATIONS.md`).
5. `/readyz` `checks.schema`: `behind` = database older than the code, `missing` = no version table.
