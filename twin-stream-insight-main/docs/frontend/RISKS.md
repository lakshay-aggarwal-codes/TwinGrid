# Accepted risks and known gaps

## Accepted

| ID | Risk | Why accepted / mitigation |
|---|---|---|
| R-1 / D-6 | **WebSocket credential in the URL query string.** Since Task 6 the client first requests a single-use ticket (`POST /auth/ws-ticket`, access token in the `Authorization` header) and connects with `/ws/live?ticket=…`; a ticket in a log is already dead (30 s, one use). **Residual:** if the ticket request fails for any reason the client falls back to `/ws/live?token=…`, and the backend still accepts it while `WS_ALLOW_QUERY_TOKEN` is on (the default). | Browsers cannot set headers on a WebSocket handshake. The error reporter redacts `token=` and `ticket=`; the backend log filter redacts both. Closing the residual = set `WS_ALLOW_QUERY_TOKEN=false` (needs `REDIS_URL`; enforced by startup rule R13) once tickets are proven in production. |
| R-2 | **Refresh token is kept in `sessionStorage`**, readable by any script that runs in the page (XSS). | Tab-scoped and gone when the tab closes; the access token is memory-only; refresh tokens are single-use with reuse detection; one in-flight refresh. `PERSIST_REFRESH_TOKEN` in `src/authClient.ts` can be set to `false` so sign-in survives nothing but the page's own memory. |
| R-3 | **`VITE_*` values are public.** | Only `VITE_API_BASE_URL` and flags are needed in production; `src/test/bundleScan.test.ts` asserts demo credentials are absent from the bundle. |
| R-4 | **Runtime errors reach an operator only if `VITE_ERROR_REPORT_URL` is set**; this repo ships no receiver. | Documented in [RELEASE.md](../../RELEASE.md). |
| R-5 | `vitest` / `@vitest/mocker` advisory (path traversal via redirect mocks), moderate. The IG-00 `npm audit` also reports `tinypool` (critical, prototype pollution to RCE, a transitive dependency of vitest) and other findings; see RELEASE.md. | Dev/test only, never in the bundle. Revisit with the test-toolchain upgrade; see RELEASE.md. |

## Known gaps (not accepted risks; owners named in [STATUS.md](STATUS.md))

Accessibility and performance evidence not yet produced; `FloorHeatmap.tsx` still present; telemetry history has no producer on a simulator-only stack; real-capture fixture set to be committed.

## Not claimed anywhere in the UI

Real-facility control, measured telemetry from the simulator, per-rack or per-zone thermal history, client-side savings/rankings/aggregates, or evaluation outcomes the backend did not state.
