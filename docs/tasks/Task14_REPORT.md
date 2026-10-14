# Task 14 — Replay and time travel (+ registry.test.ts fix)

## What changed
- **`/replay` page** (feature `replay`, nav group "Explore", viewer role; the command palette lists it as "Go to Replay"). No shared file edited.
- Timeline scrubber (pointer + keyboard: arrows, PageUp/Down, Home/End), play/pause, 1×/2×/5×/10×/30×/60×, LIVE button, window 1–168 h, previous/next alert, alert pins (shape + label; filled = unacknowledged), compare mode (B − A per measurand, arrow + word), `?t=` / `?tb=` / `?w=` URL state (debounced, other params kept).
- A replay context (`ReplayProvider`): while replaying, KPIs, charts and the 3D panel read stored samples, never the live feed. Persistent banner "REPLAY — not live" (text + icon + dotted border). Replay state belongs to the page: leaving it returns every other page to live.
- Data: `loadHistory` (cursor pagination, 5000/page, max 4 pages, never downsampled) for the five stored measurands; one failing measurand is named, all failing is an error with retry. Gaps are the backend's `/gaps`; a value is the sample at or before the time (held, labelled with its own time/age), never interpolated; invalid samples counted, not shown.
- `src/features/registry.test.ts`: dropped `node:fs`/`node:path`/`__dirname` (the 3 TypeScript errors). It now reads `App.tsx` with Vite's `?raw` import, as the repo's other source gates do. Assertions unchanged.

## Assumptions
- Stored history has only five facility-wide measurands (no inlet temp, PUE, cooling mode, per-rack data). The 3D view therefore stays in neutral "physical" colouring with the replayed values listed beside it and a visible note; nothing is tinted from data the store lacks.
- Alert pins use `GET /api/alerts` (max 200, no rack); the page says when older alerts may be missing.
- Playback ticks 4×/s (1×/s under reduced motion); one tick counts at most 1 s of wall time.
- No new env vars, dependencies or backend changes.

## Test results (real output)
- Pure logic (`logic.test.ts`, run here via an esbuild bundle + minimal vitest shim): `45 passed, 0 failed`.
- Server-render smoke of Banner, Timeline, CompareCard, ReplayChart (throwaway harness): `5 passed, 0 failed`.
- `tsc` over my files (dependencies absent, missing-module noise filtered): 0 errors in `features/replay` and `registry.test.ts`.

## Not verified
- `npm ci`, `typecheck`, `lint:ci`, `vitest`, `build` could not run (no network, no `node_modules`). `ReplayPage.test.tsx` (React Testing Library, 15 tests) is written but was not executed.
- Real browser, WebGL and pointer dragging.
