<#
 Capture the frontend contract fixtures WITHOUT Docker (Windows PowerShell 5.1+ / PowerShell 7).
 Starts the real API (uvicorn api.main:app) on a throw-away SQLite file with ENVIRONMENT=development, registers one
 operator account, runs twin-stream-insight-main/scripts/capture-contract.mjs against it, then stops the API.
 Run from the repo root with the project's .venv active:   .\scripts\capture_contract_local.ps1
 Needs: the .venv (aiosqlite is in requirements-dev.txt), Node >= 22 and `npm ci` already done in twin-stream-insight-main.

 Everything captured is SIMULATED data. Fixtures are real responses of the real API; the only edit is credential redaction.
 A SQLite capture can differ from a Postgres one in value formats; the CI job `frontend-contract` re-captures from the
 compose stack and diffs by SHAPE, so a shape difference shows up there as drift, never silently.
 This script was written without being run: if a step fails, paste the error.
#>
param(
  [int]$Port = 8765,
  [string]$Out = ''          # default: the committed fixture set; pass a folder to leave the committed set untouched
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$repo = (Get-Location).Path
$work = Join-Path $env:TEMP ('twingrid_capture_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work | Out-Null

function New-Secret([int]$Length) {
  $chars = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  $bytes = New-Object byte[] $Length
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

$opKey = New-Secret 24
$opUser = 'capture_operator'
$opPass = New-Secret 20
$dbFile = (Join-Path $work 'capture.db') -replace '\\', '/'

# Environment for the API process (it inherits these); the originals are restored in `finally`.
$names = 'ENVIRONMENT', 'DATABASE_URL', 'AUTO_CREATE_TABLES', 'JWT_SECRET_KEY', 'ALLOW_PUBLIC_REGISTRATION',
         'OPERATOR_REGISTRATION_KEY', 'CORS_ALLOWED_ORIGINS', 'REDIS_URL'
$saved = @{}
foreach ($n in $names) { $saved[$n] = [Environment]::GetEnvironmentVariable($n, 'Process') }
$env:ENVIRONMENT = 'development'
$env:DATABASE_URL = "sqlite+aiosqlite:///$dbFile"
$env:AUTO_CREATE_TABLES = 'true'
$env:JWT_SECRET_KEY = New-Secret 64
$env:ALLOW_PUBLIC_REGISTRATION = 'true'
$env:OPERATOR_REGISTRATION_KEY = $opKey
$env:CORS_ALLOWED_ORIGINS = 'http://localhost:8080'
Remove-Item Env:REDIS_URL -ErrorAction SilentlyContinue   # no Redis here: the API reports it as degraded, it does not stop

$api = $null
try {
  $python = (Get-Command python).Source
  $api = Start-Process -FilePath $python -ArgumentList '-m', 'uvicorn', 'api.main:app', '--port', "$Port" `
    -WorkingDirectory $repo -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $work 'api.out.txt') -RedirectStandardError (Join-Path $work 'api.err.txt')
  $base = "http://127.0.0.1:$Port"
  $ready = $false
  for ($i = 0; $i -lt 60; $i++) {
    if ($api.HasExited) { break }
    try { Invoke-RestMethod "$base/healthz" -TimeoutSec 2 | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 2 }
  }
  if (-not $ready) {
    Write-Host '--- API stderr (last 40 lines) ---'
    Get-Content (Join-Path $work 'api.err.txt') -Tail 40 -ErrorAction SilentlyContinue
    throw "The API did not become healthy on $base (logs in $work)."
  }
  Write-Host "API healthy on $base"

  $body = @{ username = $opUser; password = $opPass; role = 'operator' } | ConvertTo-Json
  Invoke-RestMethod "$base/auth/register" -Method Post -ContentType 'application/json' `
    -Headers @{ 'X-Admin-Key' = $opKey } -Body $body | Out-Null
  Write-Host "Registered operator '$opUser' (throw-away database)."

  Push-Location (Join-Path $repo 'twin-stream-insight-main')
  try {
    $env:TWINGRID_API_BASE_URL = $base
    $env:TWINGRID_USERNAME = $opUser
    $env:TWINGRID_PASSWORD = $opPass
    $env:CAPTURE_LIVE_FRAMES = '3'
    $sha = (git -C $repo rev-parse HEAD 2>$null)
    if ($sha) { $env:TWINGRID_BACKEND_HASH = $sha }
    if ($Out) { node scripts/capture-contract.mjs --out $Out } else { node scripts/capture-contract.mjs }
    if ($LASTEXITCODE -ne 0) { throw "capture-contract.mjs exited with $LASTEXITCODE" }
  } finally {
    Pop-Location
    foreach ($n in 'TWINGRID_API_BASE_URL', 'TWINGRID_USERNAME', 'TWINGRID_PASSWORD', 'CAPTURE_LIVE_FRAMES', 'TWINGRID_BACKEND_HASH') {
      Remove-Item "Env:$n" -ErrorAction SilentlyContinue
    }
  }
  Write-Host 'Capture finished. Review `git status` and `git diff --stat`: fixtures are real captures, never hand-edit them.'
} finally {
  if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
  foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $saved[$n], 'Process') }
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
