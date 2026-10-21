# TASK 11 REPORT: AUTH-C Visitor UX

**Status: PARTIAL.** All code and tests are written; the frontend gates (typecheck, lint, vitest, build) could NOT be run in the authoring sandbox (no network, `npm ci` impossible). Run `task_11_verify.sh` to close that gap. Nothing below claims a passing test.

## What was built (all in `twin-stream-insight-main/`)
- `src/contract/fixtures-access/index.ts`: the frozen §8.1/§8.3 example bodies (no credentials).
- `src/features/access/`: `schemas.ts` (zod), `api.ts` (typed client; every call resolves to a tagged result, never throws), `ticket.ts` ({ref, token} in sessionStorage, try/catch wrapped; `navigateTo`), `validate.ts`, `strength.ts`, `activationToken.ts`, `useRequestStatus.ts` (5 s -> 30 s backoff, paused while hidden, immediate recheck on visible/online/"Check now"), `RequestAccessForm`, `PendingPage` (`/access/pending`), `ActivatePage` (`/activate`), `AccessShell`, `FormErrorSummary`.
- `authClient.ts`: `startDemoSession()` (`POST /auth/demo-session`), `DemoError`, `DEMO_ENDED_NOTICE`, `demo` flag in the snapshot (JWT `demo` claim). No refresh token => never persisted, usable until real expiry, auto sign-out with notice at expiry, `forceRefresh` ends it. Late responses after sign-out are ignored.
- `LoginScreen.tsx`: sign-in unchanged; adds "Request viewer access" and "Explore read-only demo" (404 -> "Demo is not enabled on this server.").
- `App.tsx`: public routes `/access/pending` and `/activate` render outside `AuthGate`. `CORE_ROUTE_PATHS` gains `/access`, `/activate`.
- `AuthGate.tsx` + `DemoBanner.tsx`: persistent "Read-only demo" / "Simulated data" labels.
- `useAuth.ts`: `startDemo`.

## Decisions to review
- Request form is a view inside `LoginScreen` (not a route); after submit it navigates via `history.pushState` + `popstate` because `LoginScreen` tests render without a Router.
- Activation errors invalid/expired/used share one message because the contract returns one `invalid_or_expired` body.
- Unknown status strings from the server are treated as "unexpected" (kept polling with backoff), not guessed.
- Copy never says an email was sent; approved state says "Check your email for an activation link" (as the card specifies) and the resend note uses the server's neutral wording.
- Existing tests were not edited. New tests live in separate files.

## Tests added (not run here)
`pure.test.ts`, `api.test.ts`, `RequestAccessForm.test.tsx`, `PendingPage.test.tsx`, `ActivatePage.test.tsx`, `authClient.demo.test.ts`, `DemoBanner.test.tsx`, `LoginScreen.access.test.tsx`, `publicRoutes.test.ts`. Cover: each status state, submit, double-submit, reload recovery, polling backoff/hidden/offline, hash cleared (incl. StrictMode), keyboard reveal toggle, ARIA live regions, demo expiry.

## Verification actually performed
- Syntax check of every new/changed file with bun's transpiler: OK.
- Grep for `@ts-ignore`, `eslint-disable`, `any`: none in new files.
- NOT run (BLOCKED, no registry access): `npm run typecheck`, `npm run lint:ci`, `npm run test`, `npm run build` (incl. `bundleScan.test.ts`). Exact commands: `bash docs/roadmap/task-scripts/task_11_verify.sh`.
- Not covered: 320 px layout and reduced motion were not viewed in a browser (classes are `min-w-0`/`break-words`/stacked buttons; no animation added). Check at 320 px manually.
- Backend endpoints do not exist yet in this task's scope; UI is tested only against fixtures.

## Not shipped
`.env.example`, `docs/CLAIMS.md` (per playbook).
