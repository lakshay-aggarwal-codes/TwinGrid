# Operations: backup and restore

**Status: tooling exists; no restore drill has been recorded.** `scripts/backup.py` and `scripts/restore_verify.py`
are implemented and unit-tested for their pure helpers, but this document is not evidence of a successful restore.
Until `reports/ops/restore_drill_<date>.md` exists and shows every check passed, make no RTO, RPO or durability claim.
Allowed claim after a passing drill: "A restore from backup succeeded on `<date>` with measured RTO and RPO, on that host and data volume."

## What a backup contains
`python scripts/backup.py --out-dir backups/<stamp>` writes:

| File | Content |
|---|---|
| `twingrid.dump` | `pg_dump -Fc` of database `digital_twin`, taken through `docker compose exec db` |
| `files/models/`, `files/configs/` | copies of `models/` (including `registry.json`) and `configs/` |
| `files/data_manifests`, `files/REGISTER.json` | dataset manifests and the external-data register |
| `files/.env.example` | variable names only. `.env` is **never** copied |
| `state.json` | what a correct restore must reproduce: per-table row counts, ordered hash of `audit_logs`, telemetry count and min/max `ts_event` per stream, `alembic_version`, audit trigger presence, snapshot time |
| `backup_manifest.json` | SHA-256 and size of every file in the backup |

The dump holds database contents: treat the backup directory as sensitive. The opt-in `backup` compose service
(`docker compose --profile backup up -d backup`) provides a named volume `backup_data` mounted at `/backups`; copy dumps in with
`docker compose cp` or move them off the host.

## Running a backup (PowerShell)
```
docker compose up -d db
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
python scripts/backup.py --out-dir backups\$stamp
```

## Running the restore drill (PowerShell)
```
python scripts/restore_verify.py --backup-dir backups\<stamp> --n1-dump <dump taken at the previous schema revision>
```
Everything happens in scratch databases (`twingrid_restore_scratch`, `twingrid_restore_n1`) that are dropped at the end;
the live database is never touched. A check that cannot run is recorded as FAIL, not skipped, and the report says PASS only if
every check passed. The report is written to `reports/ops/restore_drill_<date>.md`.

Checks performed:
1. `alembic current` equals the recorded head
2. an N-1 dump upgrades to head (needs `--n1-dump`; without it this check fails)
3. row counts equal for every public table
4. `audit_logs` ordered hash equal
5. telemetry count and min/max `ts_event` per stream equal
6. artifact SHA-256 values in the restored `models/` equal `models/registry.json`
7. the audit append-only trigger (`audit_logs_append_only`) is present after restore
8. the API boots and `/readyz` returns 200 against the restored database
9. `.env.example` covers every variable the compose file requires

Observed RTO = wall time from restore start to `/readyz` 200. Observed RPO = restore start minus the backup snapshot time.
Both are measurements for one host and one data volume, not guarantees.

If any check fails: record it, fix the cause through a new task, and repeat the drill. Rollback of a drill is dropping the scratch databases.

## Secrets inventory (names only, never values)
| Name | Purpose | Where it lives |
|---|---|---|
| `JWT_SECRET_KEY` (or `JWT_SECRET_KEY_FILE`) | signs access tokens; compose requires it | environment or secret file, not in backups |
| `OPERATOR_REGISTRATION_KEY` | operator self-registration | environment or secret file |
| `METRICS_TOKEN` | bearer token for `/metrics` (mandatory in production) | environment or secret file |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | database access; compose requires `POSTGRES_PASSWORD` | environment or secret file |
| `REDIS_PASSWORD` | Redis for the task queue; compose requires it | environment |
| `ELECTRICITY_MAPS_API_KEY`, `NSRDB_API_KEY` | optional ingestion keys | environment |

Secrets are not part of a backup. After a restore on a new host, re-supply them from your secret store. A restored database
needs the same `JWT_SECRET_KEY` only if existing tokens must stay valid; otherwise users sign in again.

Variables the compose file requires (`${VAR:?}`): `JWT_SECRET_KEY`, `MQTT_BROKER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`; all four appear in `.env.example`.
