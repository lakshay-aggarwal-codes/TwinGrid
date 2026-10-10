# Accepted risks and known gaps

## Accepted

| ID | Risk | Why accepted / mitigation |
|---|---|---|
| R-1 / D-6 | **WebSocket token is sent in the URL query string** (`/ws/live?token=…`). Query strings can appear in proxy and server logs. | Browsers cannot set headers on a WebSocket handshake. Tokens are short-lived; the frontend error reporter redacts `token=`; the backend must not log it unredacted. |
| R-2 | **Refresh token is kept in `sessionStorage`**, readable by any script that runs in the page (XSS). | Tab-scoped and gone when the tab closes; the access token is memory-only; refresh tokens are single-use with reuse detection; one in-flight refresh. `PERSIST_REFRESH_TOKEN` in `src/authClient.ts` can be set to `false` so sign-in survives nothing but the page's own memory. |
| R-3 | **`VITE_*` values are public.** | Only `VITE_API_BASE_URL` and flags are needed in production; `src/test/bundleScan.test.ts` asserts demo credentials are absent from the bundle. |
| R-4 | **Runtime errors reach an operator only if `VITE_ERROR_REPORT_URL` is set**; this repo ships no receiver. | Documented in [RELEASE.md](../../RELEASE.md). |
| R-5 | `vitest` / `@vitest/mocker` 3.x advisory (path traversal via redirect mocks), moderate. | Dev/test only, never in the bundle. Revisit with the test-toolchain upgrade; see RELEASE.md. |

## Known gaps (not accepted risks; owners named in [STATUS.md](STATUS.md))

Accessibility and performance evidence not yet produced; `FloorHeatmap.tsx` still present; telemetry history has no producer on a simulator-only stack; real-capture fixture set to be committed.

## Not claimed anywhere in the UI

Real-facility control, measured telemetry from the simulator, per-rack or per-zone thermal history, client-side savings/rankings/aggregates, or evaluation outcomes the backend did not state.
