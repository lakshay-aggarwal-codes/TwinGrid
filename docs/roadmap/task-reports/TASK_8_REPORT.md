# Task 8 — RT-001 Telemetry / history reality check          Status: PARTIAL
Base: uploaded `TwinGrid-main.zip` (owner's `git status` / `git log -1 --oneline` not seen)     Date: 2026-10-20     Environment: no Docker, Postgres, network or backend dependencies; source reading only.

## Summary
Findings are in `docs/roadmap/RT-001.md`. Source evidence resolves 8 of 12 items (producer exists, dedupe, units, ordering, restart handling, backfill not consumed by any chart, two-halves rack rendering exists, UQ-1 to UQ-4 settled). Steps 1 to 3 (run the stack, 10-minute growth, UI and curl, restart) are blocked; exact commands are in `RT-001.md`. No code changed; `STATUS.md` text fixed in 5 places.

## Acceptance checklist
- Every open item has a status and evidence: met (statuses in RT-001.md; runtime evidence is `blocked`, not claimed).
- No code changed: met (only two markdown files plus this report).

## Changed files
- `docs/roadmap/RT-001.md` (new). `twin-stream-insight-main/docs/frontend/STATUS.md` (FE-18 row, open items 3 and 8, MR table row).
- `docs/roadmap/task-reports/TASK_8_REPORT.md`.

## Commands run
Source reading with `grep` / `sed` / `ls` only. No test, build or stack command.

## Pre-existing failures observed
None observed (nothing was run).

## Not run / blocked
Steps 1 to 3 of the card and the anomaly `warming_up` check: see `RT-001.md`, "Runtime checks".

## Decisions and defaults used
`STATUS.md` fixed only where source proves a sentence stale; the producer sentence now says "not yet run on a real stack".

## Requested cross-task changes
Task 23: wire backfilled samples into the chart; explain the 450 s gap threshold. Task 16: none.

## New limitations or risks
The 300 s declared interval versus a 3 s tick makes `/gaps` coarse. Database and table names in the psql commands are assumed.

## Next tasks unblocked
Task 23 (reads RT-001.md).
