# Task 28 — QA-003 Accessibility sweep          Status: PARTIAL
Base: TwinGrid-main.zip with TASK_11 overlaid (no git history; owner's working copy not seen)   Date: 2026-10-21
Environment: Node 22.22 and Bun for transpile checks only. No `node_modules`, no PyPI/npm access, no backend, no browser run, no screen reader.

## Summary
`e2e/a11y.spec.ts` is extended with the card's surfaces (alerts, what-if, optimizer approvals, report, fleet, model passport and assistant drawers, all five admin tabs incl. the access queue, request/pending/activation pages, approve-dialog focus, 320 px and 200 %-approximation reflow, reduced motion). `FE-19.md` has the route-by-route table, with every result honestly `NOT RUN`. No component was changed: nothing was measured, so no evidence-based fix exists. Status is PARTIAL because the card's acceptance needs a completed table.

## Acceptance checklist
- Table complete -> NOT MET: rows exist, results are `NOT RUN` (needs the real stack).
- No WCAG-conformance claim without a full audit -> MET: none is made, FE-19 says NOT SIGNED.
- Evidence page -> absent (no `/evidence` route; Task 26 not merged).
- Manual passes (keyboard, focus, zoom, screen reader) -> NOT DONE; parts automated, screen reader impossible here and documented.

## Changed files
- MODIFY `twin-stream-insight-main/e2e/a11y.spec.ts` — appended a Task 28 block; existing tests untouched.
- MODIFY `twin-stream-insight-main/docs/frontend/a11y/FE-19.md` — appended the Task 28 section (the path the repo actually uses; the card says `docs/frontend/a11y/`).
- CREATE `docs/roadmap/task-reports/TASK_28_REPORT.md`.

## Commands run
- `bun build e2e/a11y.spec.ts --no-bundle`: transpiles. This is syntax only, not type-checking.

## Pre-existing failures observed
None observed (nothing was run).

## Not run / blocked
`npm ci`, `npm run typecheck`, `npm run lint:ci`, `npx playwright test e2e/a11y.spec.ts`; the manual checks above.
```
cd twin-stream-insight-main
$env:E2E_VIEWER_USERNAME="..."; $env:E2E_VIEWER_PASSWORD="..."; $env:E2E_ADMIN_USERNAME="..."; $env:E2E_ADMIN_PASSWORD="..."
npm ci; npm run typecheck; npm run lint:ci
npx playwright test e2e/a11y.spec.ts
```

## Decisions and defaults used
- Used `signInAndGo`/`goClient` (client-side navigation) because the session lives in memory.
- Signed-in reflow at 320 px is soft (`expect.soft`) and attached as JSON: the shell is desktop-first and a hard gate would fail on a known design limit rather than a defect. Public pages are a hard gate.
- 200 % zoom is approximated by viewport size and labelled as such.
- Admin and approve-dialog tests need an admin account (`E2E_ADMIN_*`); the access-pages block creates one real request per run (limit 5/hour/IP).

## Requested cross-task changes
None yet; to be raised after the first real run.

## New limitations or risks
- Selector guesses that may need a tweak on first run: `getByRole("alertdialog")` for the approve dialog, `getByRole("dialog", {name: /Model passport/i})`, the `model-passport-button` first match, the `/report` heading regex `/./`.
- A failing blocking scan on a component owned by an in-flight task must be raised as a cross-task request, not edited.

## Next tasks unblocked
Task 31 (release gate) can cite FE-19 once the table has real results; Task 26 adds an evidence-page row.
