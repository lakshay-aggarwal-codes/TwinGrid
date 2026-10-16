# Task 20 report: onboarding tour, Story Mode, standard states

## What changed
- **`features/guided-tour/`**: first-run welcome (Radix dialog) and a 13-step **Story Mode** (180 s for an operator, shorter for a viewer). Pure step engine (`engine.ts`), steps (`steps.ts`), remembered welcome/resume/completed flags (`storage.ts`, localStorage, never throws), spotlight plus caption card (own overlay + Radix popover, no new dependency). Auto-advances, navigates between pages, pause/resume/back/next/skip, keys: arrows, P, Esc. Starts from the command palette (`Start Story Mode`, `Resume Story Mode`, `Show the welcome screen`).
- **`features/app-states/`**: persistent **status bar** (connection state, last-update age, data origin) shown on every signed-in page; `StateSkeleton`, `StandardState` (loading skeleton, empty, error, stale, offline, with Retry and plain wording) and `StandardBoundary`, built on the existing `StatusMessage`, `STATE_VOCABULARY` and `errorCopy`.
- Small edits: `hooks/SimulationProvider.tsx` (+4 lines: publishes the one feed to new `telemetry/activeFeed.ts`), `features/registry.test.ts` (shipped-feature list updated; it was already missing three features).

## Rules held
- Roles: steps above the signed-in role, and pages the role cannot open or that are not registered, are dropped (viewer never sees operator steps). UX only; the backend still decides.
- Captions say "simulation/simulated"; a test scans them for measured, validated, calibrated, optimal, real facility, production-ready. Origin in the bar is the backend's exact value; absent or unknown reads "Unverified source"; before any frame, "not reported yet".
- Reduced motion: the spotlight transition and skeleton pulse are off; no animation otherwise. Leaving the story's page by hand ends the tour (resume kept) rather than fighting the user.

## Assumptions
- The status bar needs the feed, but the account bar sits outside `SimulationProvider`; hence `activeFeed.ts` (same store, no second connection).
- No highlight hooks were added to existing pages: targets are found by existing labels and test ids; a missing target gives a centred caption.
- Existing screens were not rewritten to use `StandardState` (other lanes own them); it is ready to import.
- Remaining `lint:ci` warnings (3) are in Task 19 files (`PpoPanel`, `ProposalsPanel`, `RecommendationCard`), not touched here.

## Tests (real output)
- New: `engine.test.ts`, `storage.test.ts`, `TourHost.test.tsx`, `statusModel.test.ts`, `StatusBar.test.tsx`, `StandardState.test.tsx`: `Test Files 6 passed · Tests 78 passed`.
- `registry.test.ts` + `components.test.tsx` + `SimulationProvider.test.tsx`: pass.
- ESLint on all touched/new files: clean. `tsc`: no errors in touched files.
- Full `vitest` on the uploaded zip: `5 failed | 1175 passed | 14 skipped` (same 5 failing tests as before my change).

## Not verified
- The uploaded zip has no `src/runs/` (and `components/runs/`), so `npm run build`, `bundleScan` and every test that imports `apiClient` fail here before and after. My new `TourHost` and `StatusBar` tests were run with a temporary local stub of `src/runs/schema.ts` (not shipped) and pass; with your real `src/runs/` they run unchanged.
- 2 palette tests and 5 other feature tests fail identically with my folders removed (pre-existing).
- No browser: the visual placement of the spotlight, card and status bar at 360 px is untested.
