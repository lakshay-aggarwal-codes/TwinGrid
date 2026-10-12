# IG-02b — Frontend closure: dead code, motion guard, non-colour cue

Base: repo ZIP `TwinGrid-main.zip` (post IG-01). Sandbox: Node v22.22.2, clean `npm ci`, vitest/eslint/tsc from the lockfile.
Commit SHA: NOT AVAILABLE (the ZIP has no `.git`). Machine: Linux sandbox, not the owner's Windows machine.

## Changes

| # | File | Change |
|---|---|---|
| 1 | `twin-stream-insight-main/src/components/FloorHeatmap.tsx` | DELETED. No importer existed (grep over `src/`, lazy imports, `index.html`). |
| 1 | `twin-stream-insight-main/src/three/visualizationModes.ts` | Comment only (line 27): "Stage 6's FloorHeatmap fix" -> "Stage 6's heat-map fix". No code touched; no public props changed. |
| 2 | `twin-stream-insight-main/src/index.css` | Removed `.pulse-dot`, `@keyframes pulse-glow`, `@keyframes scan-line`, `.scan-line::after`. They were unused: grep over `src/` and `index.html` finds no `pulse-dot`, `pulse-glow` or `scan-line` outside `index.css`, and `tailwind.config.ts` does not reference them. Deleted, so no reduced-motion guard was needed. |
| 3 | `twin-stream-insight-main/src/components/SimulationTab.tsx` | The water bar chart ("Water consumed (L) — as reported per step") encoded cooling mode by colour only. Each mode now also has its own SVG fill pattern (Evaporative diagonal, Closed-Loop dots, Free Air horizontal, Hybrid cross, Unrecognised vertical) and a text legend (pattern swatch + mode name) listing the modes present in the run. The chart summary now says bars are "coloured and patterned". Existing summary and data table kept. Pattern ids are per-instance (`useId`). |
| 3 | `twin-stream-insight-main/src/components/SimulationTab.a11y.test.tsx` | 5 tests ADDED (none removed or weakened). |

## Evidence (real output, sandbox)

Targeted run after the changes (with the sandbox-only stub described under Findings):

```
 ✓ src/components/SimulationTab.a11y.test.tsx (9 tests)
 ✓ src/components/SimulationTab.test.tsx (10 tests)
 ✓ src/components/analyticsGate.test.ts (13 tests)
 Test Files  3 passed (3)
      Tests  32 passed (32)
```

Full suite, same stub in both runs (stub = `src/runs/schema.ts`, see Findings):

| | Test files | Tests |
|---|---|---|
| Before (base ZIP) | 10 failed, 83 passed (93) | 18 failed, 1022 passed, 14 skipped (1054) |
| After | 9 failed, 84 passed (93) | 15 failed, 1030 passed, 14 skipped (1059) |

Per-test diff of failing tests: fixed = 3 (`analyticsGate` "the file does not exist", "nothing imports it (import graph empty)", and "no * 0.4 (invented carbon factor)", the last of which was matching constants inside `FloorHeatmap.tsx`). New failures = none. The +5 tests are the new ones above.

Files still failing after (all outside this task, IG-02a's): `api/alerts.test.ts`, `api/esgReport.test.ts`, `api/facility.test.ts`, `components/shell/OperationsConsole.test.tsx`, `evaluation/schema.test.ts`, `hooks/useWhatIf.test.tsx`, `pages/Runs.test.tsx`, `telemetry/useFeed.test.tsx`, `test/bundleScan.test.ts`.

Mutation check: with the bar `Cell` fill reverted to the bare colour, 2 of the 5 new tests fail (7 pass); restored, 9/9 pass.

`npm run lint:ci` on the delivered tree (no stub):

```
> eslint . --max-warnings 0
lint exit: 0
```

`grep FloorHeatmap` over `src/`: only `analyticsGate.test.ts` (the gate asserting it is gone). `grep pulse-dot|pulse-glow|scan-line` over `src/` and `index.html`: no match.

`npm run typecheck` (sandbox): 6 errors, none in files this task touched: `ScenarioPicker.tsx(44)` x2 (IG-02a F-08) and 4 `Cannot find module` errors from the missing `src/runs/` and `src/components/runs/` directories (Finding 1).

## Findings (outside this task's ownership)

1. **P1: source directories are missing from the ZIP.** `.gitignore` line 245 is `runs/` (unanchored). It matches `twin-stream-insight-main/src/runs/` and `twin-stream-insight-main/src/components/runs/`. Neither is in the ZIP, yet `src/api/apiClient.ts` imports `../runs/schema`; `src/pages/Runs.tsx` imports `@/runs/flag`, `@/components/runs/RunMonitor` and `@/components/runs/RunStart`; and `Runs.test.tsx` imports `@/runs/testFixtures`. A clone built from tracked files will fail to build. If the ZIP was cut from git or downloaded from GitHub, those files are untracked; if it was a working-tree zip, they were excluded. NOT VERIFIED on the owner's machine (they may exist locally). Probable fix: anchor the rule (`/runs/` for a repo-root runs folder) and commit the two directories. Owner: IG-02a for the frontend load failures; `.gitignore` has no owner in Shared contract 3.2, so owner decision / IG-I.
2. To run the suite at all I used a **sandbox-only** stub `src/runs/schema.ts` (`z.any()` schemas) so imports resolve. It is not in the delivered ZIP and is not a fix. All before/after numbers above use it in both runs.
3. The cooling-mode **pie chart** ("Cooling mode by step") also encodes mode by colour. Its legend and data table name the modes, but slice colour is the only on-chart cue. Not changed (the task names the bar chart). Candidate for IG-06 or a follow-up.
4. Stale documentation mentions (not mine to edit): `docs/frontend/STATUS.md:25`, `docs/frontend/a11y/FE-19.md:37-38` and `docs/frontend/RISKS.md:15` still say `FloorHeatmap.tsx` exists. Owners: IG-17b (`STATUS.md`), IG-06 (`a11y/**`), IG-09 (`RISKS.md`).

## Claim boundary

FloorHeatmap removed; the water bar chart has a non-colour cue (pattern + text legend). No WCAG conformance claim (IG-06 owns that).

## NOT RUN

- Visual check of the patterns in a real browser or Playwright (jsdom checks fills and legend text only).
- `npm run build` and `npm run verify` (the base tree cannot build without `src/runs`; Finding 1).
- Any run on the owner's Windows machine.
