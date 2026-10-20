# Task 12 — AUTH-D Admin access-request queue     Status: DONE (frontend gates run; backend routes not yet present)
Base: TwinGrid-main.zip as uploaded (no git history)     Date: 2026-10-20
Environment: Linux container, Node 22.22, `npm ci --ignore-scripts` (the plain `npm ci` crashed here); no backend, no browser.

## Summary
New "Access requests" tab in the admin console (admin only): status filter, single-column cards, "Load more" paging with
`before_id`, details (admin-only decision note), approve/reject through a focus-managed confirmation dialog with an optional note,
in-flight lock, 409/404 handling, resend notification and resend activation. Built against the section 8.1 contract; the backend
(Task 9) does not exist yet, so nothing here has talked to a real server.

## Acceptance checklist
- Decision flow works against fixtures: met (approve, reject, note, cancel, 409, other errors, in-flight lock, focus return).
- Non-admin never sees the panel: met (viewer, operator, null, unknown role: no tab, no panel, no request).
- States (loading/empty/error/forbidden), pagination, status filter, details: met.
- 375 px layout: met as class/structure assertions (single column, no table, 44 px targets, wrapping). NOT checked in a real browser.
- Tokens never displayed: met (the schema drops unknown keys; a leak test proves it).

## Changed files
CREATE twin-stream-insight-main/src/features/admin-console/{AccessPanel.tsx, AccessPanel.test.tsx, accessApi.test.tsx, useAccessRequests.ts, accessFixtures.ts}
MODIFY twin-stream-insight-main/src/features/admin-console/{AdminPage.tsx (one tab), AdminPage.test.tsx (tab list now has 5 names), api.ts, schema.ts, model.ts} (additions only, except the one test expectation)

## Commands run (in a copy of twin-stream-insight-main with the changes)
- `npx vitest run src/features/admin-console`: 6 files, 128 tests passed
- `npx vitest run` (whole frontend): 165 files, 2059 passed, 10 skipped, 0 failed
- `npx tsc --noEmit -p tsconfig.app.json`: 16 errors, all in files this task did not touch (the same 16 recorded before); 0 in the new or changed files. `-p tsconfig.node.json`: 0 errors
- `npx eslint . --max-warnings 0`: 3 warnings, all in src/features/optimizer-approvals (pre-existing); 0 in this task's files
- `VITE_API_BASE_URL=https://api.ci.invalid npm run build`: built
- One mutation check: removing the Escape/close guard made the in-flight test fail (the lock test is not vacuous)

## Pre-existing failures observed
`npm run typecheck` (16 errors) and `npm run lint:ci` (3 warnings) already fail before this task. Not fixed here.

## Not run / blocked
Real backend (Task 9), browser at 375 px, Playwright, `npm audit`, backend tests.

## Decisions and defaults used
- The decision `note` is sent as `{}` when blank. The resend endpoints are sent with no body and only the HTTP status is checked, because section 8.1 does not specify their response.
- Access-request schema deliberately strips unknown keys (not `.passthrough()`) so a leaked token/hash can never reach the UI.
- `next_before_id` is accepted as a string or an integer (ids are uuid strings in the contract).
- "Resend notification" is offered only for a pending request whose email state is not `sent`; "Resend activation" only for `approved`.
- The tab sits second, after Users; the default tab is still Users (so the existing admin tests stay valid).
- Two extra files beyond the card's list: `useAccessRequests.ts` (hooks) and `accessFixtures.ts`/`accessApi.test.tsx`, to avoid editing `useAdmin.ts` and `testFixtures.ts`.

## Requested cross-task changes
- Task 9: the list `items` must carry `id, ref, name, email, purpose, status, created_at, expires_at, decided_at, decided_by, notify_state, notify_attempts`; the single-item route must add `decision_note`. Return `409 {"error":"invalid_transition"}` for a non-pending approve/reject, and any 2xx for the two resend routes.
- Task 10 / Task 9: the owner email links to `<base>/admin`, which opens the Users tab. A `#access` hash that opens this tab would save the owner one tap on a phone.

## New limitations or risks
Layout is asserted by class names, not visually. Contract drift in Task 9 (field names, cursor type) shows up as a "contract" error in the panel, by design.

## Next tasks unblocked
11 (visitor UX) and 13 are independent; 9 is the dependency to make this tab show real data.
