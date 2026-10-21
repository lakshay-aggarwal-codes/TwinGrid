# Task 23 — RT-003 History and backfill consumer          Status: PARTIAL
Base: TwinGrid-main.zip as uploaded (Tasks 8 and 16 already in it: docs/roadmap/RT-001.md, src/signal_state.py present). No git history; owner's working copy not checked.
Environment: Node 22.22 only; NO node_modules, vitest, tsc, eslint, jsdom, browser, backend or network.

## Summary
Backfilled samples (stored `live` telemetry for frames the browser missed) now reach the history chart through a pure merge
(`telemetry/history/backfillMerge.ts`): unit-checked, deduplicated, ordered by event time without sorting, memory-bounded, and a
shortfall is drawn as a gap, never filled. Empty history says "not stored in this mode"; gap granularity (RT-001 #5) is stated.

## Acceptance checklist
- Backfilled samples reach the chart, no fabricated points -> met in source and by pure tests -> `HistoryView` merges `useBackfillState()`; nothing is added except samples the API returned.
- Dedupe / order / gaps as gaps / bounded memory -> met (pure tests below).
- Truthful empty state when persistence is off -> met in source (`history-not-stored` line); component test not run.
- Restart / sequence regression guard -> met: `gapBetween` returns null on a seq regression (test added); no window means nothing to merge.
- Tests: gap, duplicate, reorder, unavailable history, wrong unit -> written; the 11 pure ones ran, the 5 component ones did not.
- Journey J6 on the seeded demo -> NOT run (needs the Docker stack).

## Changed files
- CREATE `twin-stream-insight-main/src/telemetry/history/backfillMerge.ts` — the merge.
- CREATE `.../telemetry/history/backfillMerge.test.ts` — 11 tests.
- CREATE `.../components/charts/HistoryViewBackfill.test.tsx` — 5 component tests.
- MODIFY `.../components/charts/HistoryView.tsx` — optional `backfill` prop, merge, notes, chart end extended to the newest recovered sample.
- MODIFY `.../components/charts/TelemetryHistoryScreen.tsx` — passes `useBackfillState()`; adds the not-stored line under the empty state (existing empty text unchanged).
- MODIFY `.../telemetry/history/model.ts` — `eventMs` exported (one word).
- MODIFY `.../features/realtime-resilience/backfill.ts` — recovered series now carry the API `unit` (optional field, needed for the unit check).
- CREATE `docs/roadmap/task-reports/TASK_23_REPORT.md`.

## Commands run
- The 11 tests in backfillMerge.test.ts, via `node --experimental-strip-types` with a throwaway vitest stand-in and a stubbed apiClient: 11 passed, 0 failed. This is NOT vitest.
- Not run: everything else.

## Pre-existing failures observed
None observed (nothing else could run).

## Not run / blocked
Run in `twin-stream-insight-main`: `npm ci; npm run typecheck; npm run lint:ci; npm run test; npm run build`. Also `/telemetry` in the browser on the demo stack (RT-001 runtime checks), which covers J6.
Unverified risks: TypeScript/ESLint errors in my edits; `sourceGate.test.ts` (I avoided `.sort`, `.reduce`, "stale", "latest", "interpolat" in non-comment text, but it was not run); the existing HistoryChart/TelemetryHistory tests (the new gap-granularity note adds one more `role="note"` when `thresholdS` is set).

## Decisions and defaults used
- Out-of-order recovered samples are dropped and counted, not re-sorted (the history source gate forbids sorting).
- Recovered samples newer than the requested window end are kept and the chart end extends to them; older than the window start are dropped.
- Shortfall (valid recovered < frames the server numbered) marks the whole backfill window as a gap, since seq numbers say frames are missing but not where.
- Unit must match exactly; an unknown recovered unit is rejected when the history unit is known.
- Cap: 5000 recovered samples per sensor (newest kept).

## Requested cross-task changes
None.

## New limitations or risks
Backfill state is app-wide and in memory only; it is lost on reload, and only the most recent gap is held. The page does not poll, so a window requested before a gap closes won't pick it up until refresh or a re-render from backfill state.

## Next tasks unblocked
None.
