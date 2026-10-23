<#
  R-Task 12: collect real results in ONE run. Windows PowerShell 5.1+ / PowerShell 7. Run from anywhere; it moves to the repo root.

  It only RUNS things and saves the raw output. It never edits code and never decides pass/fail for you.
  Output: reports\task12\<timestamp>\*.log, summary.csv, and a zip of the folder next to it. Upload the zip to Claude.

  Before you start (once):
    1. Docker Desktop is running, and the demo stack is up:      .\scripts\demo.ps1          (WITHOUT -WithFrontend)
       Copy the three demo logins it prints (demo_viewer, demo_operator, demo_admin).
    2. In THIS terminal, set the e2e accounts (the passwords from step 1):
         $env:E2E_VIEWER_USERNAME="demo_viewer";     $env:E2E_VIEWER_PASSWORD="..."
         $env:E2E_OPERATOR_USERNAME="demo_operator"; $env:E2E_OPERATOR_PASSWORD="..."
         $env:E2E_ADMIN_USERNAME="demo_admin";       $env:E2E_ADMIN_PASSWORD="..."
    3. Nothing is listening on http://localhost:8080 (Playwright starts its own dev server, without demo auto-login).
    4. The Python venv is active (.\.venv\Scripts\Activate.ps1).

  Usage:   .\scripts\task12_collect.ps1                       (backend + frontend gates, audits, Playwright)
           .\scripts\task12_collect.ps1 -IncludeDrills        (also the db/redis/mail drill scripts; needs Git Bash)
           .\scripts\task12_collect.ps1 -IncludePerf          (also scripts\perf_task29.ps1; LAST, it restarts the stack with limits off)
           .\scripts\task12_collect.ps1 -SkipPlaywright       (gates and audits only)
#>
param(
  [switch]$IncludeDrills,
  [switch]$IncludePerf,
  [switch]$SkipPlaywright,
  [switch]$SkipGates,          # skip the backend/frontend/audit gates (round1_collect.ps1 already covers them)
  [string]$ApiUrl = "http://localhost:8000",
  [int]$PauseSeconds = 65
)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$repo = (Get-Location).Path
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$out = Join-Path $repo ("reports\task12\" + $stamp)
New-Item -ItemType Directory -Force $out | Out-Null
$rows = New-Object System.Collections.ArrayList

function Run-Step {
  param([string]$Name, [scriptblock]$Block)
  $log = Join-Path $out ($Name + ".log")
  Write-Host ""
  Write-Host "==> $Name" -ForegroundColor Cyan
  $global:LASTEXITCODE = 0
  $t0 = Get-Date
  & $Block 2>&1 | Tee-Object -FilePath $log | Out-Host
  $code = $global:LASTEXITCODE
  $secs = [int]((Get-Date) - $t0).TotalSeconds
  [void]$rows.Add([pscustomobject]@{ step = $Name; exit_code = $code; seconds = $secs; log = ($Name + ".log") })
  Write-Host "    exit code $code, $secs s" -ForegroundColor DarkGray
}

# ---- 0. environment record (no secrets: only the NAMES of the e2e variables, never their values)
$envLines = @()
$envLines += "date: $(Get-Date -Format o)"
$envLines += "commit: $(git rev-parse --short HEAD 2>&1)"
$envLines += "git status (short):"
$envLines += (git status --short 2>&1)
$envLines += "python: $(python --version 2>&1)"
$envLines += "node: $(node --version 2>&1)   npm: $(npm --version 2>&1)"
$envLines += "docker: $(docker --version 2>&1)"
$envLines += "os: $((Get-CimInstance Win32_OperatingSystem).Caption) $((Get-CimInstance Win32_OperatingSystem).Version)"
$envLines += "e2e variables set: " + ((Get-ChildItem Env: | Where-Object { $_.Name -like "E2E_*" } | ForEach-Object { $_.Name }) -join ", ")
$envLines | Out-File (Join-Path $out "00_environment.txt") -Encoding utf8

# ---- 1. preflight (warnings only; the steps below still run and record whatever happens)
$pre = @()
foreach ($n in "E2E_VIEWER_USERNAME", "E2E_VIEWER_PASSWORD", "E2E_OPERATOR_USERNAME", "E2E_OPERATOR_PASSWORD", "E2E_ADMIN_USERNAME", "E2E_ADMIN_PASSWORD") {
  if (-not (Get-Item "Env:$n" -ErrorAction SilentlyContinue)) { $pre += "MISSING env var $n (Playwright specs that sign in will fail)" }
}
try { $h = Invoke-WebRequest "$ApiUrl/healthz" -UseBasicParsing -TimeoutSec 10; $pre += "API $ApiUrl/healthz -> $($h.StatusCode)" }
catch { $pre += "API $ApiUrl/healthz NOT reachable: start the stack with .\scripts\demo.ps1" }
try { $null = Invoke-WebRequest "http://localhost:8080" -UseBasicParsing -TimeoutSec 3; $pre += "WARNING: something already answers on :8080. If it was started with VITE_DEMO_USERNAME/PASSWORD the sign-in specs will fail." }
catch { $pre += "port 8080 is free (good: Playwright starts its own dev server)" }
if (-not $env:VIRTUAL_ENV) { $pre += "WARNING: no Python venv is active" }
$pre | Out-File (Join-Path $out "01_preflight.txt") -Encoding utf8
$pre | ForEach-Object { Write-Host "preflight: $_" -ForegroundColor Yellow }

# ---- 2. backend gates
if (-not $SkipGates) {
Run-Step "10_backend_pytest" { pytest tests -m "not postgres" -rs -q --timeout=300 --timeout-method=thread --show-capture=no -p no:cacheprovider }
if ($env:TWINGRID_TEST_PG_URL) { Run-Step "11_backend_pytest_postgres" { pytest tests -m postgres -rs -q --timeout=300 --timeout-method=thread } }
else { "TWINGRID_TEST_PG_URL not set: the Postgres suite was NOT run." | Out-File (Join-Path $out "11_backend_pytest_postgres.NOT_RUN.txt") -Encoding utf8 }
Run-Step "12_ruff_check" { ruff check . }
Run-Step "13_ruff_format" { ruff format --check . }
Run-Step "14_alembic_heads" { alembic heads }
Run-Step "15_pip_audit" { pip-audit --requirement requirements.lock --require-hashes --disable-pip --strict }
}

# ---- 3. frontend gates
Push-Location (Join-Path $repo "twin-stream-insight-main")
if (-not $env:VITE_API_BASE_URL) { $env:VITE_API_BASE_URL = $ApiUrl }
if (-not $env:VITE_ERROR_REPORT_URL) { $env:VITE_ERROR_REPORT_URL = "$ApiUrl/api/client-errors" }
Remove-Item Env:VITE_DEMO_USERNAME -ErrorAction SilentlyContinue
Remove-Item Env:VITE_DEMO_PASSWORD -ErrorAction SilentlyContinue
Run-Step "20_npm_ci" { npm ci }
if (-not $SkipGates) { Run-Step "21_frontend_verify" { npm run verify } }
if (-not $SkipGates) { Run-Step "22_npm_audit" { npm audit --audit-level=high } }

# ---- 4. Playwright against the real stack, one spec per run, paused so the 10/min sign-in limiter is not what fails
if (-not $SkipPlaywright) {
  $specs = "a11y", "stale-surfaces", "real-backend", "viewer-workflow", "assistant", "drills"
  foreach ($s in $specs) {
    Run-Step ("30_playwright_" + $s) { npx playwright test ("e2e/" + $s + ".spec.ts") --reporter=list }
    Write-Host "    pausing $PauseSeconds s (sign-in rate limit)..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $PauseSeconds
  }
}
Pop-Location

# ---- 5. optional: failure drills (shell scripts: Git Bash or WSL)
if ($IncludeDrills) {
  $bash = "C:\Program Files\Git\bin\bash.exe"
  if (Test-Path $bash) {
    foreach ($d in "drill_db_down", "drill_redis_down", "drill_mail_failure") {
      Run-Step ("40_" + $d) { & $bash ("scripts/" + $d + ".sh") }
    }
  } else { "Git Bash not found at ${bash}: drills NOT run (run them in WSL: sh scripts/drill_db_down.sh etc.)." | Out-File (Join-Path $out "40_drills.NOT_RUN.txt") -Encoding utf8 }
}

# ---- 6. optional: performance (restarts the stack with request limits OFF, so it goes last)
if ($IncludePerf) {
  if (-not $env:TWINGRID_USERNAME) { $env:TWINGRID_USERNAME = $env:E2E_VIEWER_USERNAME; $env:TWINGRID_PASSWORD = $env:E2E_VIEWER_PASSWORD }
  Run-Step "50_perf_task29" { & (Join-Path $repo "scripts\perf_task29.ps1") }
}

# ---- 7. summary + zip
$rows | Export-Csv (Join-Path $out "summary.csv") -NoTypeInformation -Encoding utf8
Write-Host ""
$rows | Format-Table step, exit_code, seconds -AutoSize | Out-Host
$zip = "$out.zip"
Compress-Archive -Path (Join-Path $out "*") -DestinationPath $zip -Force
if (Test-Path "reports\perf\2026-10") { Write-Host "Perf raw files are under reports\perf\2026-10 : zip that folder too if you ran -IncludePerf." -ForegroundColor Yellow }
Write-Host "Done. Upload this file to Claude: $((Resolve-Path $zip).Path)" -ForegroundColor Green
Write-Host "Skim the logs first: they should hold no passwords, but check before you share them." -ForegroundColor Yellow
