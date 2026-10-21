# Task 29 runner. Run from the repo root in PowerShell, with Docker Desktop up. Every step writes a raw file under
# reports\perf\2026-10\; a step that fails is recorded, nothing is estimated. Read reports\perf\2026-10\README.md first.
# Required env: TWINGRID_USERNAME / TWINGRID_PASSWORD (a viewer or operator account), E2E_VIEWER_USERNAME / E2E_VIEWER_PASSWORD.
$ErrorActionPreference = "Continue"
$out = "reports\perf\2026-10"; New-Item -ItemType Directory -Force $out | Out-Null
$api = "http://localhost:8000"
$compose = @("--env-file", ".env.demo", "-f", "docker-compose.yml", "-f", "docker-compose.demo.yml")

# 0. Environment record (hardware, versions). Fill the data-scale and concurrency lines in README.md by hand.
Get-ComputerInfo | Select-Object CsProcessors, CsNumberOfLogicalProcessors, CsTotalPhysicalMemory, OsName, OsVersion | ConvertTo-Json | Out-File "$out\environment_host.json" -Encoding utf8
"python: $(py -3.12 --version)  node: $(node --version)  docker: $(docker --version)  commit: $(git rev-parse --short HEAD)" | Out-File "$out\environment_versions.txt" -Encoding utf8

# 1. Start the stack with request limits OFF (limits would return 429 and hide latency). Record that in README.md.
$env:HTTP_LIMITS_ENABLED = "false"
.\scripts\demo.ps1

# 2. Store >= 5,000 simulator samples per sensor (writes into the running database).
py -3.12 scripts\perf_seed_history.py --ticks 5000 --stream import:perf-2026-10 2>&1 | Tee-Object "$out\seed_history.log"

# 3. API latency, 1 client then 8 clients. History is read from the seeded stream.
foreach ($c in 1, 8) {
  py -3.12 scripts\perf_endpoints.py --base-url $api --requests 300 --concurrency $c --limits false --history-stream import:perf-2026-10 --out "$out\api_endpoints_c$c.json" 2>&1 | Tee-Object "$out\api_endpoints_c$c.log"
}

# 4. Database timing of the history query at the seeded size (plan and execution time as the database reports them).
$sql = "select count(*) as rows_in_stream from telemetry_sample where stream_id = 'import:perf-2026-10'; explain (analyze, buffers) select * from telemetry_sample ts join sensor s on s.id = ts.sensor_id where s.external_id = 'fac1.it_power_kw' and ts.stream_id = 'import:perf-2026-10' and ts.ts_event >= now() - interval '24 hours' order by ts.ts_event, ts.id limit 5001;"
docker compose @compose exec -T db psql -U postgres -c $sql 2>&1 | Tee-Object "$out\db_history_query.txt"

# 5. WebSocket message and freshness delay (30 clients + 1 stalled), and the simulator micro-benchmark.
$env:LOAD_USER = $env:TWINGRID_USERNAME; $env:LOAD_PASSWORD = $env:TWINGRID_PASSWORD
py -3.12 scripts\ws_load.py ws --base-url $api --connections 30 --stalled 1 --duration 120 --run-id t29-ws --scenario ws30 --out "$out\ws_load_t29.json" 2>&1 | Tee-Object "$out\ws_load_t29.log"
py -3.12 scripts\bench_suite.py --sections twin --out "$out\bench_twin.json" 2>&1 | Tee-Object "$out\bench_twin.log"

# 6. Frontend: bundle size and the Playwright perf spec (page interaction, paint, 3D frame behaviour). Smoke length soak only.
Push-Location twin-stream-insight-main
npm ci
npm run build 2>&1 | Tee-Object "..\$out\frontend_build.log"
$env:PERF = "1"; $env:PERF_SOAK_MINUTES = "2"; $env:PERF_WRITE_RESULTS = "1"; $env:PERF_DIST = "dist"
npx playwright test e2e/perf.spec.ts 2>&1 | Tee-Object "..\$out\frontend_perf_spec.log"
Pop-Location
Write-Host "Done. Now fill reports\perf\2026-10\README.md from the raw files. Budgets come only after this baseline."
