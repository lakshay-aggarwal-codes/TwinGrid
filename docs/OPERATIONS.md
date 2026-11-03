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
| `COPILOT_LLM_<NAME>_API_KEY` (or `_API_KEY_FILE`) | optional model-provider key, one per provider (`GROQ`, `OPENROUTER`, ...); a local Ollama needs none | environment or secret file |

Secrets are not part of a backup. After a restore on a new host, re-supply them from your secret store. A restored database
needs the same `JWT_SECRET_KEY` only if existing tokens must stay valid; otherwise users sign in again.

Variables the compose file requires (`${VAR:?}`): `JWT_SECRET_KEY`, `MQTT_BROKER`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`; all four appear in `.env.example`.

## Copilot: local-only mode, provider failover and the docs index

The assistant answers from rules and cited evidence. A language model is **off by default**; when on, it may only rephrase
that answer, and the rule-based text is always the last fallback. Limits and data flow: `docs/model_cards/copilot.md`.
Commands are Windows PowerShell from the repo root.

### Local-only mode (nothing leaves the machine)

```powershell
winget install Ollama.Ollama
ollama pull llama3.2:3b
```

In `.env` (names only below; pick the model tag that fits your RAM):

```
COPILOT_LLM_ENABLED=true
COPILOT_LLM_PROVIDERS=ollama
COPILOT_LLM_OLLAMA_MODEL=llama3.2:3b
COPILOT_LLM_OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
COPILOT_LLM_LOCAL_ONLY=true
COPILOT_LLM_BUDGET_S=45
```

The `OLLAMA_BASE_URL` line is for a backend in Docker and Ollama on the host; leave it out when the backend runs on the host.
Then `docker compose restart backend` and check the local model with `python -m src.copilot.local` (exit code 0 means up).
With `COPILOT_LLM_LOCAL_ONLY=true` every provider not flagged local is dropped, so a cloud name in the list is never contacted.

### Cloud failover chain (different providers only)

```
COPILOT_LLM_PROVIDERS=ollama,groq,openrouter
COPILOT_LLM_GROQ_MODEL=<model id from the provider's list>
COPILOT_LLM_GROQ_API_KEY_FILE=<path to a file holding the key>
```

The chain is tried in order within `COPILOT_LLM_BUDGET_S`. One provider, one account, one key: never list several accounts of
one provider to get more quota. Cloud providers serve documentation questions only unless `COPILOT_LLM_CLOUD_INTENTS` lists
more intents. Presets, client-side limits and the unverified data-use terms: `docs/copilot/PROVIDERS.md`.

Two-provider demo (local first, cloud second), with the docs index built (see below) and the backend running from a checkout:

1. Set `COPILOT_LLM_PROVIDERS=ollama,groq` and make the local provider unreachable: `COPILOT_LLM_OLLAMA_BASE_URL=http://localhost:9/v1`.
2. Restart the backend and ask a documentation question (below). The answer should carry `provider.name = groq` and
   `provider.fell_back = true`; the log shows `llm_chain outcome=ok attempts=ollama:<unavailable word>,groq:ok`.
3. Restore the real Ollama URL and restart.

```powershell
$cred = Get-Credential
$body = @{ username = $cred.UserName; password = $cred.GetNetworkCredential().Password } | ConvertTo-Json
$tok = (Invoke-RestMethod -Method Post -Uri http://localhost:8000/auth/login -ContentType 'application/json' -Body $body).access_token
$q = @{ question = 'What does the runbook say to do when the API is down?' } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/copilot/ask -Headers @{ Authorization = "Bearer $tok" } -ContentType 'application/json' -Body $q
$r.mode; $r.provider; $r.warnings; $r.citations.source_path
```

### Replace a provider key

Revoke the old key at the provider, put the new one in the environment or the `_API_KEY_FILE` file, then restart the backend.
The restart matters: a 401 or 403 disables that provider until the process restarts. Never write a key into a ticket or a log.
Other secrets: `docs/runbooks/rotating-secrets.md`.

### What an outage looks like

| What you see | Meaning |
|---|---|
| Answer badge `Rule-based explanation` with a note that the model did not answer; warning `llm_unavailable` | every provider failed or was skipped; the rule-based answer is complete and correct |
| Warning `llm_rejected` | a model reply broke the checks (a number, link or word the evidence does not hold) and was thrown away |
| Warning `llm_blocked_by_policy` | local-only mode or the per-intent cloud rule left no provider for that question |
| Warning `llm_busy` | `COPILOT_LLM_MAX_CONCURRENT` chains were already running |
| Warning `docs_index_unavailable` or `docs_index_stale` | documentation answers are off until the index is rebuilt |

Failed providers cool down (60 s doubling to 900 s after a 429; 30 s base for other failures). State is per process. The
Copilot never returns an error to the client because a provider failed. Runbooks: `docs/runbooks/copilot-providers-down.md`,
`docs/runbooks/copilot-index-stale.md`.

### Rebuild the docs index

The index is a build artifact (`data/copilot/docs_index.sqlite`, or `COPILOT_DOCS_INDEX_PATH`), never committed. It must match
the documents on disk: if any indexed document changed, the Copilot treats the index as stale and stops answering from the docs.

```powershell
python scripts/build_copilot_index.py --check
python scripts/build_copilot_index.py
python scripts/build_copilot_index.py --query "api down"
```

A running server re-checks within about 60 s; no restart is needed.

### Docker note

`.dockerignore` excludes every `*.md`, so the backend image holds no documents and cannot build or check the index: in the
supplied Docker stack, documentation answers report `docs_index_unavailable`, while rule-based answers and model phrasing work.
For documentation answers run the backend from a checkout (`CONTRIBUTING.md`), or mount the documents and the index into the
container yourself; that mount has not been tried.
