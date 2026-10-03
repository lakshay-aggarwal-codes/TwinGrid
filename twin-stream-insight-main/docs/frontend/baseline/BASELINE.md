# FE-00 Baseline verification record

Evidence only. Nothing under `src/**` (or any other pre-existing file) was changed. A SHA-256 manifest of the tree taken before and after all commands shows no differences (excluding `node_modules`, `dist`, `test-results`, which are build/run output).

## Environment

| Item | Value |
|---|---|
| Frontend root | `twin-stream-insight-main/` (nested inside the supplied `TwinGrid-main` archive) |
| Node / npm | v22.22.2 / 10.9.7. Satisfies `engines` (`>=22.20.0 <23`); `.nvmrc` pins 22.20.0. `engines` not touched. |
| Git | Not a git repository (supplied as a ZIP), so `git status` is unavailable. A `T0b.diff` file is present at the frontend root; left untouched. |
| Sandbox | Linux container, no IPv6 support, Playwright browser download blocked |
| Backend roadmap | `TwinGrid_Backend_Roadmap_PostT9.md` not supplied and not present in the archive (see `BACKEND_RECONCILIATION.md`) |

## Script results

| Command | Result | Log |
|---|---|---|
| `npm ci` | PASS (exit 0); prints 10 vulnerabilities | `logs/npm-ci.log` |
| `npm run typecheck` | PASS | `logs/typecheck.log` |
| `npm run lint:ci` (`--max-warnings 0`) | PASS: 0 errors, 0 warnings | `logs/lint-ci.log` |
| `npm run lint` | PASS, no output | `logs/lint-nocap.log` |
| `npx eslint . --max-warnings 7` | PASS | `logs/lint-cap7.log` |
| `npm run test` | **FAIL**: 6 failed, 112 passed (118 tests); 1 of 18 files failed | `logs/test.log` |
| `npm run build` (as shipped, no env) | **FAIL** (exit 1): the production env guard refuses to build because `VITE_API_BASE_URL`, `VITE_DEMO_USERNAME`, `VITE_DEMO_PASSWORD` are unset. This is the documented guard, not a code defect. | `logs/build.log` |
| `npm run verify` | **FAIL** (exit 1) at the `test` stage; `build` is never reached | `logs/verify.log` |
| `npm run test:e2e` | **FAIL / not executed** (exit 1); see E2E below | `logs/e2e.log` |
| `npm audit` | exit 1: 10 vulnerabilities (2 moderate, 8 high) | `logs/audit.log`, `logs/audit.json` |
| `npm audit --audit-level=high` (the CI gate per `RELEASE.md`) | **FAIL** (exit 1) | `logs/audit-high.log` |

## Unit tests: pass/fail per file

| Test file | Tests | Result |
|---|---|---|
| `src/api/apiClient.test.ts` | 5 pass, **6 fail** | **FAIL** |
| `src/authClient.test.ts` | 25 | pass |
| `src/components/AuthGate.test.tsx` | 5 | pass |
| `src/components/LoginScreen.test.tsx` | 6 | pass |
| `src/components/SustainabilityTab.test.tsx` | 1 | pass |
| `src/components/shell/OperationsConsole.test.tsx` | 1 | pass |
| `src/components/shell/RackInspectorContent.test.tsx` | 1 | pass |
| `src/components/shell/TwinHeader.test.tsx` | 8 | pass |
| `src/components/transition/RotateTransition.test.tsx` | 13 | pass |
| `src/config.test.ts` | 3 | pass |
| `src/hooks/SimulationProvider.test.tsx` | 2 | pass |
| `src/hooks/liveness.test.ts` | 12 | pass |
| `src/hooks/useSimulation.anomaly.test.tsx` | 8 | pass |
| `src/hooks/useSimulation.liveness.test.tsx` | 7 | pass |
| `src/lib/errorReporter.test.ts` | 5 | pass |
| `src/test/bundleScan.test.ts` | 2 | pass |
| `src/test/example.test.ts` | 1 | pass |
| `src/three/rackNavigation.test.ts` | 7 | pass |

Totals: 18 files (17 pass, 1 fail); 118 tests (112 pass, 6 fail).

## Verdict: does `apiClient.test.ts` fail against `apiClient.ts`?

**Yes.** 6 of its 11 tests fail against the current `src/api/apiClient.ts`. The tests specify behaviour the source does not implement.

| Failing test | Evidence |
|---|---|
| `authedFetch > on 401 refreshes once and retries with the new token` | `authedFetch` (L189) calls `getToken()` once and returns the `fetch` response; it never checks for 401 and never calls `forceRefresh`. The 401 reaches `handleResponse` (L181) and throws "Invalid or expired token". |
| `authedFetch > does not loop: a second 401 surfaces as an error after one retry` | Expected `fetch` called 2 times, got 1: there is no retry. |
| `authedFetch > propagates AuthRequiredError when the session is gone` | `forceRefresh` is never invoked, so a plain `Error` with `status: 401` is thrown instead of `AuthRequiredError`. |
| `connectWebSocket > reconnects immediately with a FRESH token when the server closes with 4002` | `ws.onclose` (L358) handles all close codes identically (schedules a delayed reconnect); there is no 4002 branch. Only 1 socket exists after 10 ms where 2 are expected. |
| `connectWebSocket > backs off on other closes and does NOT reset the backoff just because the socket opened (cap rejection)` | `ws.onopen` (L372) resets `reconnectDelay` to the default, but the test expects the delay to keep growing (3000, 4500, 6750 ms) across open-then-close cycles. Got 3 sockets where 2 were expected. |
| `connectWebSocket > resets the backoff once the server actually streams` | The source resets the delay on `onopen`, not on first received message. Got 2 sockets where 3 were expected. |

Passing in the same file: `sends the bearer token`; `does not treat 403 as an auth failure`; `connects with the current access token in the query string`; `stops reconnecting when there is no session any more`; `disconnect() closes the socket and cancels a pending reconnect`.

`src/authClient.ts` does export `forceRefresh` and `AuthRequiredError` (L35, L278) and `authClient.test.ts` passes, so the gap is in how `apiClient.ts` consumes the auth client. Per FE-00 nothing was fixed. I have not determined which side (tests or source) is the intended contract; only that they disagree.

## Lint warning cap discrepancy

| Source | Claim |
|---|---|
| `package.json` `lint:ci` | `eslint . --max-warnings 0` |
| `RELEASE.md` | `--max-warnings 7`; 7 accepted `react-refresh/only-export-components` warnings in `components/ui/*` |
| Measured | 0 errors, **0 warnings**; both the 0 and 7 caps pass |

`package.json` matches reality. `RELEASE.md` is stale on the cap and on the "7 known warnings".

## Audit

`npm audit`: 10 vulnerabilities, **2 moderate, 8 high**. `RELEASE.md` records "2 moderate, 0 high/critical" and says CI runs `npm audit --audit-level=high`; that gate currently exits 1.

- Moderate: `@vitest/mocker` / `vitest` (GHSA-82fw-gwwq-j7x9), matching `RELEASE.md`; fix is vitest 5 (breaking).
- High: `braces` (GHSA-vfj7-8cjw-p6xm, stack-exhaustion DoS; npm reports "No fix available") and its dependants `micromatch`, `fast-glob`, `chokidar`, `tailwindcss`, `@tailwindcss/typography`, `lovable-tagger`, `tailwindcss-animate`. These appear to be build/dev tooling by dependency graph; whether any reaches the shipped bundle was not verified here. The advisory database has likely changed since `RELEASE.md` was written.

## Bundle sizes

The shipped `npm run build` cannot run without env vars. As a **supplementary** measurement only, it was run with shell-provided placeholder values (`VITE_API_BASE_URL=https://api.example.invalid`, dummy demo credentials; no env files written). That build passed (`logs/build-with-placeholder-env.log`):

| Asset | Raw | Gzip |
|---|---|---|
| `assets/three-*.js` | 807.24 kB | 218.63 kB |
| `assets/index-*.js` | 595.97 kB | 196.87 kB |
| `assets/Index-*.js` | 581.99 kB | 170.36 kB |
| `assets/index-*.css` | 63.63 kB | 11.34 kB |
| `index.html` | 1.06 kB | 0.51 kB |
| `twingrid-logo.png` (public) | 1,132,179 B | n/a |

`dist/` totals 3.1 MB. Vite warns that three chunks exceed 500 kB, and that `VITE_ERROR_REPORT_URL` is unset.

## E2E (`npm run test:e2e`): no result obtained

No Playwright test ran. Two environment blockers, recorded and not worked around (config files are out of scope):

1. `playwright.config.ts` starts `npm run dev`, and `vite.config.ts` binds `host: "::"`. That fails in this sandbox: `listen EAFNOSUPPORT: address family not supported :::8080` (`logs/e2e.log`).
2. Chromium is not installed and `npx playwright install chromium` could not download it (`logs/playwright-install.log`).

The status of `e2e/smoke.spec.ts` is therefore **unknown**, not passing. Re-run in an environment with IPv6 and browsers.

## Summary

1. `apiClient.test.ts` fails against `apiClient.ts` (6 tests): 401 refresh/retry and WebSocket 4002/backoff behaviour are tested but not implemented.
2. `npm run verify` fails at `test`; the build is blocked by missing env (by design).
3. `RELEASE.md` is stale: lint cap/warnings (actual 0) and audit counts (actual 8 high).
4. `npm audit --audit-level=high` currently fails.
5. E2E result unknown because of sandbox limits.
