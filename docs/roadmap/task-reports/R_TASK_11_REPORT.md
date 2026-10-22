# R Task 11 report: missing drills

## Summary
Harnesses written for the three drills the RC matrix listed as "none": sequence restart (`e2e/drills.spec.ts`), history gap (`scripts/drill_history_gap.sh`), large data (`scripts/drill_large_data.sh`). RC_REPORT.md drill rows updated; every Observed cell stays empty and every Result stays NOT RUN until you run them.

## Acceptance checklist
- Every drill row has a harness or a stated reason: met for these three. The LLM timeout row is Task 10's and was not touched.
- "Observed" filled only by a real run: met (none filled).
- Task 23 backfill consumer exists: confirmed in source (`src/telemetry/history/backfillMerge.ts`, `features/realtime-resilience/BackfillHost.tsx`). Not exercised in a browser here: the gap drill checks the server side only.

## Changed files
CREATE `scripts/drill_large_data.sh`, `scripts/drill_history_gap.sh`; MODIFY `twin-stream-insight-main/e2e/drills.spec.ts`, `docs/roadmap/RC_REPORT.md` (three drill rows); CREATE this report.

## Commands run
`sh -n` on both scripts; `py_compile` on the Python embedded in each; an offline check of the gap-timeline arithmetic (one gap of 600 s above 450 s, a 420 s hole below it); a brace/paren balance count on the spec.

## Not run
Everything that needs Docker, the demo stack, a browser or `npx playwright` / `tsc`: all three drills, and the existing spec's typecheck.

## Decisions used
Seq-restart drill observes frames with `routeWebSocket` (forwarded unchanged) and waits for seq >= 20 before stopping the backend, so the restart shows as a regression. Drill data uses fresh `import:drill-*` streams, origin `simulated`, values from `DigitalTwin.step`.

## Requested cross-task changes
None.
