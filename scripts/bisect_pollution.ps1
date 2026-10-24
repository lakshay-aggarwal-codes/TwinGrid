<#
  Finds which group of EARLIER tests makes the "late" tests fail, without re-running the whole 18-minute suite each time.
  Usage (repo root, venv active):   .\scripts\bisect_pollution.ps1            # splits the earlier tests into 4 chunks
                                    .\scripts\bisect_pollution.ps1 -Chunks 6
  For each chunk it runs: <that chunk of earlier test files> followed by the late files, and prints which late tests FAILED.
  A chunk whose run shows failures contains a test that leaves state behind. It writes reports\bisect\<stamp>.txt (UTF-8).
#>
param([int]$Chunks = 4)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$root = (Get-Location).Path

# The files that fail only in the full run (test_task9_api_reference is fixed and is left out on purpose).
$late = @(
  "tests/test_baselines.py", "tests/test_notify_mail.py", "tests/test_repro_framework.py",
  "tests/test_task6_security.py", "tests/test_task7_observability.py",
  "tests/test_telemetry_ingest.py", "tests/test_train_ppo.py"
)
$skip = $late + @("tests/test_task9_api_reference.py", "tests/test_load_harness.py")

$all = Get-ChildItem tests -Recurse -Filter "test_*.py" | Sort-Object FullName | ForEach-Object {
  ($_.FullName.Substring($root.Length + 1)) -replace '\\', '/'
}
$early = @($all | Where-Object { $skip -notcontains $_ })
$size = [math]::Ceiling($early.Count / $Chunks)

$stamp = Get-Date -Format "yyyyMMdd-HHmm"
New-Item -ItemType Directory -Force "reports\bisect" | Out-Null
$out = "reports\bisect\$stamp.txt"
"early test files: $($early.Count), chunks: $Chunks, files per chunk: $size" | Tee-Object -FilePath $out

for ($i = 0; $i -lt $Chunks; $i++) {
  $part = @($early | Select-Object -Skip ($i * $size) -First $size)
  if ($part.Count -eq 0) { continue }
  $label = "chunk $($i + 1)/$Chunks  ($($part[0]) ... $($part[-1]))"
  Write-Host ""
  Write-Host "==> $label" -ForegroundColor Cyan
  Add-Content $out "" -Encoding utf8
  Add-Content $out "==> $label" -Encoding utf8
  $lines = pytest @part @late -m "not postgres" -q --tb=line --show-capture=no --timeout=300 --timeout-method=thread -p no:cacheprovider 2>&1
  $failed = @($lines | Where-Object { $_ -match '^FAILED ' })
  $summary = ($lines | Where-Object { $_ -match ' (passed|failed)' } | Select-Object -Last 1)
  Add-Content $out "summary: $summary" -Encoding utf8
  Write-Host "summary: $summary"
  foreach ($f in $failed) {
    $short = $f.Substring(0, [Math]::Min(200, $f.Length))
    Add-Content $out $short -Encoding utf8
    Write-Host $short
  }
  if ($failed.Count -eq 0) { Write-Host "  (no late test failed after this chunk)" -ForegroundColor Green; Add-Content $out "  (no late test failed after this chunk)" -Encoding utf8 }
}
Write-Host ""
Write-Host "Done. Paste the lines above, or upload $out" -ForegroundColor Green
