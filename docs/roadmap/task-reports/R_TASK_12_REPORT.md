# R-Task 12: Real-stack results

Status: **PARTIAL (collection tooling delivered; no results exist yet)**

## Summary
Task 12 needs Docker, a browser and your demo stack, which Claude's sandbox does not have. Nothing was measured here and no table was filled.
Delivered: `scripts/task12_collect.ps1`, one PowerShell script that runs every Task 12 check against your real stack and saves raw output to `reports\task12\<timestamp>\` plus a zip. Claude fills the tables only from that zip.

## Acceptance checklist
| Criterion | Result |
|---|---|
| No table cell says NOT RUN without a named blocker | NOT MET: waiting for your run output |
| Accessibility table, performance baseline, drill Observed/Result filled from real output | NOT MET: same |

## Changed files
- CREATE `scripts/task12_collect.ps1`
- CREATE `docs/roadmap/task-reports/R_TASK_12_REPORT.md`

## Not run / blocked
Everything. The script itself was **never executed**: no PowerShell in the authoring sandbox, so it was written and read-checked only. If it errors, paste the error; do not hand-edit results.

## What the script runs (each step logs separately, with its exit code in summary.csv)
Backend: full pytest (not postgres), Postgres suite if `TWINGRID_TEST_PG_URL` is set, ruff check and format, `alembic heads`, pip-audit. Frontend: `npm ci`, `npm run verify`, `npm audit --audit-level=high`. Playwright, one spec per run with a pause for the 10/min sign-in limiter: a11y, stale-surfaces, real-backend, viewer-workflow, assistant, drills. Optional: `-IncludeDrills` (db/redis/mail shell drills via Git Bash), `-IncludePerf` (existing `scripts\perf_task29.ps1`, runs last because it restarts the stack with limits off).

## Not covered (needs separate action)
- Anomaly held-out evaluation and baselines refresh (TensorFlow/torch): optional, see `docs/roadmap/ML-002_RUNBOOK.md`.
- `alembic check` and downgrade drill: need a database URL; `drill_clean_install.sh` covers it.
- Screen-reader and manual keyboard/zoom passes (Task 28): human only.

## Requested cross-task changes
None.
