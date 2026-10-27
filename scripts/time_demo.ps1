<#
.SYNOPSIS
  Stopwatch for the demo script in docs/DEMO_CHECKLIST.md (R3 Task 13).
.DESCRIPTION
  Reads the steps of the "## Demo script" section, then for each run: you press Enter to start the clock, do the step,
  press Enter when it is done, and type a note only if something broke or was skipped (the clock is paused while you type).
  Writes reports\task13\demo_timing_<time>.csv. Times are your Enter presses, so each is good to about a second.
  Nothing is measured but what you do; run it twice, in a fresh private window, with the demo stack already up.
.EXAMPLE
  .\scripts\time_demo.ps1            # two runs
  .\scripts\time_demo.ps1 -Runs 1
#>
param(
    [int]$Runs = 2,
    [string]$Checklist = "docs\DEMO_CHECKLIST.md",
    [string]$OutDir = "reports\task13"
)

$lines = Get-Content -LiteralPath $Checklist
$start = ($lines | Select-String -Pattern '^## Demo script' | Select-Object -First 1).LineNumber
if (-not $start) { throw "No '## Demo script' section in $Checklist" }

$steps = @()
for ($i = $start; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^## ') { break }
    if ($lines[$i] -match '^\|\s*(\d+)\.\s*([^|]+?)\s*\|') {
        $steps += [pscustomobject]@{ N = [int]$Matches[1]; Name = $Matches[2] }
    }
}
if ($steps.Count -eq 0) { throw "No numbered steps found under '## Demo script' in $Checklist" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$rows = @()
for ($r = 1; $r -le $Runs; $r++) {
    Write-Host ""
    Write-Host "Run $r of $Runs, $($steps.Count) steps. Open a fresh private window, then press Enter to start the clock."
    $null = Read-Host
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $prev = 0.0
    foreach ($s in $steps) {
        Write-Host ("Step {0}: {1}   (press Enter when done)" -f $s.N, $s.Name)
        $null = Read-Host
        $now = $sw.Elapsed.TotalSeconds
        $sw.Stop()
        $note = Read-Host "  What broke or was skipped? (Enter for nothing)"
        $sw.Start()
        $rows += [pscustomobject]@{
            run        = $r
            step       = $s.N
            name       = $s.Name
            seconds    = [math]::Round($now - $prev, 1)
            cumulative = [math]::Round($now, 1)
            note       = $note
        }
        $prev = $now
    }
}

$file = Join-Path $OutDir ("demo_timing_{0}.csv" -f (Get-Date -Format "yyyyMMdd-HHmm"))
$rows | Export-Csv -LiteralPath $file -NoTypeInformation -Encoding UTF8
Write-Host ""
$rows | Format-Table run, step, name, seconds, cumulative, note -AutoSize
$rows | Group-Object run | ForEach-Object { "run {0}: total {1} s" -f $_.Name, [math]::Round(($_.Group | Select-Object -Last 1).cumulative, 1) }
"written: " + (Resolve-Path -LiteralPath $file).Path
