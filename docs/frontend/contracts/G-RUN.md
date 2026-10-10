# G-RUN: Contract Confirmation Record (BC-10 run/job contract)

**STATUS: CAPTURED IN A SANDBOX, NOT YET ON THE REAL BACKEND.**
CAPTURE 1 and 3 are complete. CAPTURE 2 is real output of the BC-10 route, service and worker-job code, produced by an
in-process app with an in-memory Redis (details below), not by your running backend. **Repeat CAPTURE 2 against the real
backend (runbook below); FE-16 starts only after that diff is clean.**

## Contract (backend)

A run is one scenario from `GET /api/scenarios` (BC-09, G-SCN) executed as a queued job: one isolated 24 h what-if on the
simulated plant, the same computation as `GET /api/whatif`. Three endpoints, all JWT, any role:

| endpoint | purpose | rate limit |
|---|---|---|
| `POST /api/runs` | submit; returns `202` + run record, header `Location: /api/runs/{run_id}` | `whatif` bucket (30/min) + general |
| `GET /api/runs/{run_id}` | status record | general (120/min) |
| `GET /api/runs/{run_id}/result` | result; `409` until `status = completed` | general (120/min) |

**Submit body:** `{ "scenario_id": string, "parameters"?: { utilisation?, outside_temp?, water_stress?, mode?, chilled_water_temp? } }`.
Parameter names are the descriptor names from `/api/scenarios`; bounds are the registry bounds. `parameters` override the preset key by
key (override > preset, same rule as `/api/whatif`). Unknown `scenario_id` gives 404, out-of-range or unknown keys 422, queue down 503.

**Run record** (submit response and `GET /api/runs/{run_id}`; always these 12 keys):
`run_id, kind, status, scenario_id, scenario_set_id, registry_version, parameters, created_at, started_at, ended_at, failure_code, result_url`.

- `run_id`: UUID string, chosen by the backend. `kind`: `whatif` (the only kind today).
- `parameters`: the five resolved values, always all five, descriptor names (`outside_temp`, not `outside_temp_C`).
- `created_at`, `started_at`, `ended_at`: aware UTC ISO-8601 (`+00:00`), backend clock; `started_at` / `ended_at` are `null` until they happen.
- `failure_code`: `null` unless `failed`. `result_url`: `null` unless `completed`.
- There is **no `progress`, no ETA, no `unavailable` status**.

**Status set (exactly five):**

| status | meaning |
|---|---|
| `queued` | accepted, no worker has started it (also what you see if no worker is running) |
| `running` | a worker is computing it |
| `completed` | finished; fetch `result_url` |
| `failed` | see `failure_code` |
| `cancelled` | stopped/cancelled in the queue backend. **No API cancels a run today**; the status exists so the client has a defined state if one is cancelled operationally |

`failure_code` is one of `invalid_input`, `timeout`, `worker_lost`, `internal_error`. Nothing else about a failure (message, traceback,
path) is ever returned.

**Result** (`GET /api/runs/{run_id}/result`):
`run_id, kind, scenario_id, scenario_set_id, registry_version, parameters, started_at, ended_at, provenance, outputs`.

- `result.run_id` is the run's own id (the backend refuses to return a result whose id differs). FE-16 must still check `result.run_id === id`.
- `provenance`: `origin` (`simulated`), `scenario_kind`, `weather_source` (`constant_input`), `plant` (`simulated`), `control` (`none`),
  `physics_version`, `model_version` (`null`: a what-if applies no learned model), `carbon_data_is_real`.
  There is no dataset id and no weather-series id; weather is one held outside temperature. Show "not reported", do not infer.
- `outputs`: `hours, basis, mean_pue, wue, total_water_L, total_energy_kwh, total_co2_kg, max_outlet_temp_C, final_cooling_mode,
  drought_override_active, carbon_data_is_real`. Equal to the `/api/whatif` body minus `inputs` and `scenario_id` (test
  `test_result_equals_the_synchronous_whatif`). **Naming trap:** inputs are returned once, as `parameters` with descriptor names; there is no
  `inputs.outside_temp_C` in a run result.

**`scenario_set_id`** = `sset-<registry_version>-<first 12 hex of sha256 of the full registry payload>`, e.g. `sset-1-1d29e4177772`.
It is computed from every descriptor (ids, kinds, sources, parameter schema, bounds, preset values), so any registry change gives a new id.
Two runs with equal `scenario_set_id` were defined by the same registry content. It does **not** cover physics version (compare
`provenance.physics_version`) and it is not a hash of one run's parameters. It is **not** added to `GET /api/scenarios`: that body is
frozen by G-SCN. The sandbox value should equal your real backend's value, because the registry file hash is identical (Capture 1).

**Retention and access.** State lives in Redis only (no table, no migration). A run and its result are kept `RUN_RESULT_TTL_SECONDS`
(default 86400) after it ends; after that its id is a 404, same as an id that never existed. A run is readable by the user who submitted it and
by operators; anyone else, a non-UUID, and any non-run job id (for example a training job) get 404.

**Not provided (do not build UI for these):** cancel, run listing/history, progress, ETA, idempotency key, WebSocket push, runs of kind
`simulate` or `optimize` (BC-10 asked for those; only `whatif` is implemented), a dataset/weather identity.
Polling guidance: runs finish in well under a second on a free worker, so poll `GET /api/runs/{id}` starting around 500 ms with backoff;
the general limit is 120 requests/min per user.

## CAPTURE 1: backend content hash
Sandbox copy (the supplied repo snapshot with BC-09 applied), sha256 of the files this change adds:

| file | sha256 |
|---|---|
| `api/services/run_service.py` | `d6414ff0cc742eda46cd18e84e9d384d0225b13f0d8ea98defb8636d375d7c52` |
| `api/routes/run_routes.py` | `850d06512ee1804d5ce124cfab1bc700aef2ec8ea8ce0aeb304157c2c94dc08f` |
| `api/schemas/runs.py` | `381685318fc3acabc8cac6c4b0a8b547fe7e5c0244ddf3589e88b65c63c7a7a7` |
| `src/run_jobs.py` | `bd0fdd38563873ac3ca190e8dd7c9aa0ea0aca4a3ccef9f9588ae7b3fe3ead3d` |

Files the change depends on but does not modify (sandbox values; the first must equal the G-SCN record):

| file | sha256 |
|---|---|
| `api/services/scenario_registry.py` | `132742b9930286e84ac054be45ed87b54a39255bdff5a7ffb26d9743a51ee82f` |
| `src/task_queue.py` | `cf8c9dce3608cbc1e2cff49f9ca85e8e59de952230af7325ea10190fb1e88f23` |

`api/main.py` is edited by two lines (PowerShell below) and is checkout-specific, so it is not hashed. On the real checkout, record
`git rev-parse HEAD` and run:
```powershell
git rev-parse HEAD
Get-FileHash api\services\run_service.py, api\routes\run_routes.py, api\schemas\runs.py, src\run_jobs.py, api\services\scenario_registry.py, src\task_queue.py -Algorithm SHA256
Select-String -Path api\main.py -Pattern "run_routes"
```
The four new files must match the first table; `scenario_registry.py` must match G-SCN. If `src\task_queue.py` differs, check that
`enqueue()` still forwards `job_id`, `meta`, `result_ttl`, `failure_ttl` to RQ (the run service relies on that) before continuing.

## CAPTURE 2: response bodies
**How it was produced:** the real `run_routes` router, `run_service`, `run_jobs.run_whatif_job`, the real BC-09 registry and the real twin
computation, mounted in the real `api.main` app (real JWT register/login, in-memory SQLite). The queue was `fakeredis` and the worker a real
`rq.SimpleWorker` with the same `JSONSerializer` as docker-compose's `worker` service, so each run went enqueue -> worker -> result for real.
**Not exercised:** a real Redis server, the forking `rq worker` process and its container, Postgres, docker. In the sandbox
`carbon_data_is_real` is `false` (no carbon CSV); numeric outputs and timestamps will differ on your backend. Observed statuses on that run:

- `G-RUN.capture-submit.json`: `POST /api/runs` body for `whatif-heat-wave`, HTTP 202, `Location` header set.
- `G-RUN.capture-status-queued.json`: status before the worker ran.
- `G-RUN.capture-result-not-ready-409.json`: result requested while queued (problem+json, HTTP 409).
- `G-RUN.capture-status-completed.json`, `G-RUN.capture-result.json`: after the worker ran.
- `G-RUN.capture-status-failed-forced.json`: a **forced** failure (the computation was monkeypatched to raise), to show the failed shape; it is
  not a naturally occurring failure.

Other codes observed: unknown run id 404; unknown `scenario_id` 404; `outside_temp: 99` 422; no token 401.

## CAPTURE 3: enum set observed
`status` observed: `queued`, `completed`, `failed` (forced). **Not observed end to end:** `running` (unit test sets the RQ state directly) and
`cancelled` (mapping unit-tested only). `failure_code` observed: `internal_error`; `invalid_input`, `timeout`, `worker_lost` are covered by the
mapping unit test only, not by a real occurrence. `kind` = {`whatif`}. `provenance.origin` = {`simulated`}.

## To capture on the real backend (PowerShell, from the backend checkout root)
Prerequisite: the G-SCN stack from its runbook is up with the BC-10 files applied and the image rebuilt (`docker compose build; docker compose up -d`),
and the `worker` service is running (`docker compose ps` shows it; runs stay `queued` forever without it).
```powershell
$base = "http://localhost:8000"
$pw = Read-Host "gscn-check password"
$t = (Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" -Body (@{username="gscn-check";password=$pw} | ConvertTo-Json)).access_token
$h = @{ Authorization = "Bearer $t" }

# submit
$r = Invoke-WebRequest -Method Post -Uri "$base/api/runs" -Headers $h -ContentType "application/json" -Body '{"scenario_id":"whatif-heat-wave"}'
$r.StatusCode; $r.Headers.Location            # expect 202 and /api/runs/<uuid>
$r.Content | Out-File -Encoding utf8 real-run-submit.json
$run = $r.Content | ConvertFrom-Json
$run.scenario_set_id                            # expect sset-1-1d29e4177772

# poll until terminal, recording the statuses seen
$seen = @()
for ($i = 0; $i -lt 100; $i++) {
  $s = Invoke-RestMethod -Uri "$base/api/runs/$($run.run_id)" -Headers $h
  if ($seen.Count -eq 0 -or $seen[-1] -ne $s.status) { $seen += $s.status }
  if ($s.status -in 'completed','failed','cancelled') { break }
  Start-Sleep -Milliseconds 100
}
$seen -join " -> "
$s | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 real-run-status.json

# result
Invoke-RestMethod -Uri "$base/api/runs/$($run.run_id)/result" -Headers $h | ConvertTo-Json -Depth 10 | Out-File -Encoding utf8 real-run-result.json

# key-set diffs against the committed captures (empty output = same keys)
$k = { param($f) (Get-Content $f -Raw | ConvertFrom-Json).PSObject.Properties.Name | Sort-Object }
Compare-Object (& $k docs\frontend\contracts\G-RUN.capture-submit.json) (& $k real-run-submit.json)
Compare-Object (& $k docs\frontend\contracts\G-RUN.capture-status-completed.json) (& $k real-run-status.json)
Compare-Object (& $k docs\frontend\contracts\G-RUN.capture-result.json) (& $k real-run-result.json)

# queued is only visible with the worker stopped
docker compose stop worker
$q = Invoke-RestMethod -Method Post -Uri "$base/api/runs" -Headers $h -ContentType "application/json" -Body '{"scenario_id":"whatif-drought"}'
(Invoke-RestMethod -Uri "$base/api/runs/$($q.run_id)" -Headers $h).status          # expect queued
try { Invoke-RestMethod -Uri "$base/api/runs/$($q.run_id)/result" -Headers $h } catch { $_.Exception.Response.StatusCode.value__ }   # expect 409
docker compose start worker; Start-Sleep 5
(Invoke-RestMethod -Uri "$base/api/runs/$($q.run_id)" -Headers $h).status          # expect completed

# negative checks
curl.exe -s -o NUL -w "%{http_code}`n" -X POST -H "Content-Type: application/json" -d '{\"scenario_id\":\"whatif-baseline\"}' "$base/api/runs"   # 401
try { Invoke-RestMethod -Uri "$base/api/runs/00000000-0000-0000-0000-000000000000" -Headers $h } catch { $_.Exception.Response.StatusCode.value__ }  # 404
try { Invoke-RestMethod -Method Post -Uri "$base/api/runs" -Headers $h -ContentType "application/json" -Body '{"scenario_id":"nope"}' } catch { $_.Exception.Response.StatusCode.value__ }  # 404
try { Invoke-RestMethod -Method Post -Uri "$base/api/runs" -Headers $h -ContentType "application/json" -Body '{"scenario_id":"whatif-heat-wave","parameters":{"outside_temp":99}}' } catch { $_.Exception.Response.StatusCode.value__ }  # 422
Remove-Item real-run-*.json
```
Expected on the real backend: `$seen` ends in `completed` (it will usually read just `queued -> completed` or `completed`; `running` lasts milliseconds
and is likely missed, which is why it is flagged unobserved above); the three key-set diffs are empty; `scenario_set_id` equals the sandbox value;
`provenance.physics_version` is whatever your worker's `PHYSICS_VERSION` resolves to (record it).

## Verification actually run
- `tests/test_runs.py`: 39 tests pass in the sandbox (submit/status/result lifecycle through a real RQ worker, override precedence, 401/404/409/422/503,
  foreign-user and training-job-id isolation, failure-code mapping with no leaked text, status mapping, result-id guard, result equals `/api/whatif`).
- `tests/test_scenarios.py` (14) still passes; the G-SCN contract (`GET /api/scenarios`, `/api/whatif`) is untouched.
- Wider regression subset (`tests/api`, smoke, security, auth, serialization, ws/fanout): identical pass/fail set before and after this change, except
  `test_two_hundred_clients_one_stalled...`, which is timing-flaky on the untouched tree too (1 of 3 reruns fails on each tree). The 49 other failures in that
  subset exist on the untouched snapshot in the sandbox and are unrelated.
- **Not run:** anything against real Redis, docker, Postgres; the full suite.

## Open decisions for you
1. `scenario_set_id` as defined above (registry-content hash) is my reading of "same scenario set". If BC-11's evaluation "scenario-set id" will mean a
   chosen batch of scenarios, tell me before FE-17 so the two don't collide.
2. `unavailable` is not a run status. A down queue is HTTP 503 on submit/status; a stopped worker is indistinguishable from `queued`.
3. `simulate` and `optimize` runs are not covered (optimize needs persistence, audit and the operator role; `GET /api/simulate` still persists on request).
