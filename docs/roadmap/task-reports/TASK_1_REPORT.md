# Task 1 — BASE-001 Exact-tree baseline run and failure ledger     Status: PARTIAL
Base: TwinGrid-main.zip (no history; local `baseline` tag)     Date: 2026-10-20
Environment: Linux container, Python 3.13.16 / 3.12.3, Node 22.22.0; no PyPI access, no Postgres/Docker; npm install crashed.

## Summary
The live gates (pytest, ruff, pyrefly, pip-audit, alembic, frontend typecheck/lint/test/build) could not run here, so this task is PARTIAL. Delivered: BASELINE.md, a 21-row failure ledger built from the junit logs inside the ZIP (labelled inherited), a source-verified diagnosis of the recommendation-test failures, and confirmation of TG-A-05 and four other defects. Re-run §3 of BASELINE.md on a full environment to close the task.

## Acceptance checklist
- Ledger covers 100% of failures: NOT MET for this tree (only the 13 recorded failures + inherited groups; no live run).
- No "all pass" claim: MET.
- Every inherited claim re-checked marked confirmed/refuted: PARTLY (source-checkable ones confirmed: PUE tuple, tuner /2 vs /3, docs/api absent, what-if 5..15, TG-A-05 resolved; test results themselves remain inherited).
- 20.5 vs 10.0 cause: MET (BASELINE.md §5).

## Changed files
docs/roadmap/BASELINE.md; docs/roadmap/failure-ledger.csv; docs/roadmap/task-reports/TASK_1_REPORT.md; reports/baseline-2026-10/{check_register.txt,compileall.txt}

## Commands run
- compileall (3.13.16): exit 0 (syntax only)
- scripts/check_register.py: OK (15 datasets), exit 0
- junit XML parse: t7_junit_0 655/25 failed/5 skipped; t7_junit_2 624/13/1 (inherited)

## Pre-existing failures observed
Not applicable (nothing executed).

## Not run / blocked
All commands in BASELINE.md §3 (pytest incl. Postgres, ruff, pyrefly, pip-audit, alembic, npm ci/typecheck/lint/test/build/audit).

## Decisions and defaults used
Did not search for mirror credentials; treated the 401 as a hard blocker.

## Requested cross-task changes
Task 5: remove legacy-scale expectations (10.0, 12.0, 5..15) from test_task19_optimizer_rules.py and build a PID-wins fixture instead of using the shipped config. Register: TG-A-05 -> RESOLVED-BY-REMOVAL.

## New limitations or risks
Ledger rows for the 13 failures reflect a Windows run of 624 tests; they may not reproduce on this tree.

## Next tasks unblocked
None are hard-blocked by this; Tasks 3–9 can proceed with their own focused baselines.
