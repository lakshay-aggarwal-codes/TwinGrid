<#
  TwinGrid Round 1: collect real results, NO Docker needed.
  Put this file in the repo's scripts\ folder, activate the venv, then run:   .\scripts\round1_collect.ps1
  It only RUNS checks and saves raw output (UTF-8) to reports\round1\<timestamp>\ plus a zip. It never edits code.
  Upload the zip it prints at the end.
#>
param(
  [string]$ApiUrl = "https://api.example.invalid",   # dummy URL, only so the production build guard passes
  [int]$LocustTimeoutSeconds = 150
)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$repo = (Get-Location).Path
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$out = Join-Path $repo ("reports\round1\" + $stamp)
New-Item -ItemType Directory -Force $out | Out-Null
$rows = New-Object System.Collections.ArrayList

function Run-Step {
  param([string]$Name, [scriptblock]$Block)
  $log = Join-Path $out ($Name + ".log")
  Write-Host ""
  Write-Host "==> $Name" -ForegroundColor Cyan
  "" | Out-File $log -Encoding utf8
  $global:LASTEXITCODE = 0
  $t0 = Get-Date
  & $Block 2>&1 | ForEach-Object { $line = "$_"; Add-Content -Path $log -Value $line -Encoding utf8; Write-Host $line }
  $code = $global:LASTEXITCODE
  $secs = [int]((Get-Date) - $t0).TotalSeconds
  [void]$rows.Add([pscustomobject]@{ step = $Name; exit_code = $code; seconds = $secs; log = ($Name + ".log") })
  Write-Host "    exit code $code, $secs s" -ForegroundColor DarkGray
}

# ---- 00 environment
$e = @()
$e += "date: $(Get-Date -Format o)"
$e += "commit: $(git rev-parse --short HEAD 2>&1)"
$e += "branch: $(git rev-parse --abbrev-ref HEAD 2>&1)"
$e += "git status (short):"
$e += (git status --short 2>&1)
$e += "python: $(python --version 2>&1)"
$e += "venv: $env:VIRTUAL_ENV"
$e += "node: $(node --version 2>&1)   npm: $(npm --version 2>&1)"
$e += "pytest: $(pytest --version 2>&1)"
$e | Out-File (Join-Path $out "00_environment.txt") -Encoding utf8

# ---- 10 backend: full suite (the locust file is run separately below because it hangs)
Run-Step "10_pytest_full" { pytest tests -m "not postgres" --ignore=tests/test_load_harness.py -q -rfEs --show-capture=no --tb=short --timeout=300 --timeout-method=thread -p no:cacheprovider }

# ---- 11 locust test, with a hard timeout so it cannot freeze the run
Write-Host ""
Write-Host "==> 11_load_harness (timeout $LocustTimeoutSeconds s)" -ForegroundColor Cyan
$log11 = Join-Path $out "11_load_harness.log"
$job = Start-Job -ScriptBlock { param($r) Set-Location $r; pytest tests/test_load_harness.py -q -rfEs --show-capture=no --tb=short -p no:cacheprovider 2>&1 | ForEach-Object { "$_" } } -ArgumentList $repo
if (Wait-Job $job -Timeout $LocustTimeoutSeconds) {
  Receive-Job $job | Out-File $log11 -Encoding utf8
  $code11 = 0
} else {
  Stop-Job $job
  "TIMED OUT after $LocustTimeoutSeconds s: the locust import hang is still there." | Out-File $log11 -Encoding utf8
  $code11 = 124
}
Remove-Job $job -Force
[void]$rows.Add([pscustomobject]@{ step = "11_load_harness"; exit_code = $code11; seconds = $LocustTimeoutSeconds; log = "11_load_harness.log" })

# ---- 12 the open ledger items, one at a time with long tracebacks, so each cause can be proven
Run-Step "12a_facility_migration" { pytest tests/test_facility_migration.py -q -rfEs --tb=long -p no:cacheprovider }
Run-Step "12b_gitignore" { pytest tests/test_gitignore_source_dirs.py -q -rfEs --tb=long -p no:cacheprovider }
Run-Step "12c_physics_v1_api" { pytest tests/api/test_physics_v1_api.py -q -rfEs --tb=long -p no:cacheprovider }
Run-Step "12d_error_contract" { pytest tests/api/test_error_contract.py -q -rfEs --tb=short -p no:cacheprovider }
Run-Step "12e_build_evidence" { pytest tests/test_build_evidence.py -q -rfEs --tb=long -p no:cacheprovider }
Run-Step "12f_baselines" { pytest tests/test_baselines.py -q -rfEs --tb=long -p no:cacheprovider }
Run-Step "12g_artifact_gate" { pytest tests/test_artifact_gate.py -q -rfEs --tb=short -p no:cacheprovider }
Run-Step "12h_authz_matrix" { pytest tests/test_authz_matrix.py -q -s -rfEs --tb=short -p no:cacheprovider }
Run-Step "12i_demo_and_copilot" { pytest tests/api/test_demo_session.py tests/test_copilot_adversarial.py tests/test_copilot_llm.py tests/test_signal_state.py -q -rfEsx --tb=short --show-capture=no -p no:cacheprovider }
Run-Step "12j_smtp_capture" { pytest tests/api/test_task22_smtp_capture.py -q -rfEs --tb=short -p no:cacheprovider }

# ---- 13 lint, format, migrations
Run-Step "13_ruff_check" { ruff check . }
Run-Step "14_ruff_format" { ruff format --check . }
Run-Step "15_alembic_heads" { alembic heads }
Run-Step "16_git_check_ignore" { git check-ignore -v src api tests docs scripts alembic models }

# ---- 20 frontend
Push-Location (Join-Path $repo "twin-stream-insight-main")
$env:VITE_API_BASE_URL = $ApiUrl
$env:VITE_ERROR_REPORT_URL = "$ApiUrl/api/client-errors"
Remove-Item Env:VITE_DEMO_USERNAME -ErrorAction SilentlyContinue
Remove-Item Env:VITE_DEMO_PASSWORD -ErrorAction SilentlyContinue
Run-Step "20_npm_ci" { npm ci }
Run-Step "21_typecheck" { npm run typecheck }
Run-Step "22_lint_ci" { npm run lint:ci }
Run-Step "23_vitest_verbose" { npx vitest run --reporter=verbose }
Run-Step "24_build" { npm run build }
Run-Step "25_npm_audit" { npm audit --audit-level=high }
Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:VITE_ERROR_REPORT_URL -ErrorAction SilentlyContinue
Pop-Location

# ---- 30 python dependency audit
Run-Step "30_pip_audit" { pip-audit --requirement requirements.lock --require-hashes --disable-pip --strict }

# ---- summary + zip
$rows | Export-Csv (Join-Path $out "summary.csv") -NoTypeInformation -Encoding utf8
Write-Host ""
$rows | Format-Table step, exit_code, seconds -AutoSize | Out-Host
$zip = "$out.zip"
Compress-Archive -Path (Join-Path $out "*") -DestinationPath $zip -Force
Write-Host "Done. Upload this file to Claude: $((Resolve-Path $zip).Path)" -ForegroundColor Green
Write-Host "Skim the logs first: they should hold no passwords, but check before sharing." -ForegroundColor Yellow
