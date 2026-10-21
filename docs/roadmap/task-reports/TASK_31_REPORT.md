# Task 31 - REL-002 Release-candidate gate and failure drills          Status: BLOCKED
Base: TwinGrid-main.zip + TASK_11 overlay   Date: 2026-10-21   Environment: Node/Bun transpile only; no Docker, DB, browser or project Python packages.

## Summary
The gate cannot be run here and the card's precondition (all P0/P1 delivered) is not met: Tasks 21, 25, 26, 27 and 30 have no deliverable, Task 22 diverges from its card, and every delivered task is PARTIAL. Delivered: drill harness (shell and Playwright), `RC_REPORT.md` with the prerequisite audit, step table and drill matrix (all NOT RUN), verdict BLOCKED.

## Acceptance checklist
- Every drill row has expected/observed/result -> NOT MET: expected and result are filled, observed is empty for all (nothing ran); 4 rows are not drillable yet.
- Verdict justified by evidence only -> MET: BLOCKED, with reasons.

## Changed files
CREATE `docs/roadmap/RC_REPORT.md`, `twin-stream-insight-main/e2e/drills.spec.ts`, `scripts/drill_common.sh`, `drill_db_down.sh`, `drill_redis_down.sh`, `drill_mail_failure.sh`, `drill_clean_install.sh`, this report. No existing file edited; no defect fixed.

## Commands run
`sh -n` on every drill script: OK. `bun build --no-bundle e2e/drills.spec.ts`: transpiles (syntax only). Nothing else.

## Not run / blocked
Everything in RC_REPORT sections 2 and 3, with commands.

## Decisions and defaults used
Drills that need infrastructure control are shell scripts against the compose demo stack; browser drills use the real backend and intercept nothing. The WebSocket/stale drill is the existing `stale-surfaces.spec.ts`, not duplicated.

## Requested cross-task changes
Realign Task 22 to the AUTH-F card; deliver 21, 25, 26, 27, 30.

## New limitations or risks
Drill expectations for `/readyz` come from the route's docstring, not from a run. The scripts have never executed.

## Next tasks unblocked
None. Task 32 should not start from a BLOCKED verdict except for the parts that do not depend on it.
