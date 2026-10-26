# R_L7: browser end-to-end, drills (R1 Task 11) and audits

**Verdict: PARTIAL.** R1 Task 11 (the missing drills) is DONE: every drill that was written has now run and passed. L7 as a whole stays open because of one product finding (AI-D-3, below) and two audit decisions.

All evidence below is output pasted by the owner from runs on the owner's Windows machine on 2026-10-24/25/26 (Docker Desktop 4.82, Node 24.18 with the project asking for 22.20, Playwright 1.63 / Chromium 153). Claude could not run any of it. Stack: the `twingrid-demo` compose project, freshly reseeded (simulated data), with `docker-compose.e2e-local.yml` (local, untracked) enabling the public demo, a 1-minute demo session, trusted proxy headers and file/SMTP mail for the viewer-workflow suite.

## R1 Task 11: the drills
| Drill | Result | Evidence |
|---|---|---|
| Sequence restart (real backend stop/start, the page recovers without a stale-looking value) | PASS | `drills.spec.ts`, `E2E_DRILL_RESTART=1` |
| Token expiry (demo session ends with a notice, no data stays on screen) | PASS | `E2E_DRILL_DEMO_SHORT=1`, backend `DEMO_SESSION_MINUTES=1` |
| Unknown / empty data (explicit not-found, not an empty success) | PASS | |
| Refresh mid-approval (status still right after reloads) | PASS after a test fix | the default admin filter hides a decided request; the drill now selects "all", as `viewer-workflow.spec.ts` does |
| Dead links (malformed and unknown tokens give the same dead-link page) | PASS after a product fix | see Product changes |
| `drill_db_down.sh` | PASS 6/6 (rerun) | the first run failed (`/readyz` 200 while "stopped"); not reproduced, likely run against the wrong compose project; manual check showed 503 with `database: fail`, then 200 after start |
| `drill_redis_down.sh` | PASS 5/5 (rerun, project pinned) | |
| `drill_mail_failure.sh` | PASS 3/3 after a script fix | the compose files do not forward `ACCESS_NOTIFY_*`, so the failing SMTP settings never reached the backend; the script now writes a throw-away override file and restores the stack on exit |
| `drill_history_gap.sh` | PASS 9/9 | exactly one 600 s gap reported, the 420 s hole not reported, nothing invented |
| `drill_large_data.sh` | PASS 12/12 | 5,200 samples per sensor, cursor paging, 422 on bad limit/cursor/span |
| `drill_clean_install.sh` | NOT RUN | destructive (`down -v`); deliberately skipped |
The browser drills' last full run is `drills_pw4`: 5 passed. An earlier run failed only in teardown (`ENOENT` on Playwright's own `test-results\.playwright-artifacts-*` files; no assertion failed); cause not established; a rerun with `--output C:\twlogs\pw-out` was clean.

## Browser suites
- a11y: 48 passed (5.0 min). stale-surfaces: 1 passed. real-backend: 1 passed.
- viewer-workflow: 6 of 6 across passes. `[file]`, `[api]` (429 with Retry-After) and both `[demo]` tests in the file/demo pass; both `[smtp]` tests pass (one needed a test fix: the 44 px touch target was measured while the dialog's 200 ms zoom-in animation was still running; it is now retried until at rest).
- assistant: AI-D-1 and AI-D-2 pass after a test fix (the detector gauge and its passport live on `/analytics` since the Live Twin redesign, so the spec navigates there client-side). **AI-D-3 FAILS (open, see below).**

## Open product finding: dead "Explain this" on pages without the assistant host
AI-D-3 opens an alert on `/alerts` and clicks "Explain this". The backend access log for the run shows the alert detail loading (`/api/alerts/.../events`) but no `/api/alerts/.../explanation` and no `/api/copilot/ask`. From the code: the drawer is mounted only by `AssistantHost`, which sits in the `header-actions` slot rendered by `TwinHeader` (`/`) and `DashboardHeader` (`/analytics`); `AlertsPage` has its own plain header with no slot, so `ExplainButton` only changes store state and nothing opens. NOT yet confirmed by hand in the browser. Proposed fix: keep the "Ask" button in the slot and mount one global drawer at app level (needs the assistant unit tests adjusted).

## Product changes made in this task
- `ActivatePage`: a token that is not 43 URL-safe characters (the backend issues `secrets.token_urlsafe(32)`) now gets the dead-link page instead of the password form. Unit-test fixtures use a 43-character token; one new test covers a malformed token.

## Audits (collector run 2026-10-24; unchanged since)
- Backend suite: 5695 passed, 3 skipped (environment: header the client refuses to send, no symlinks on Windows, Windows closed-port SMTP timing), 0 failed. ruff and ruff-format clean. One alembic head, `20261101000000`.
- pip-audit on the lock: 3 lines in 2 packages (`ecdsa` PYSEC-2026-1325, `python-jose` PYSEC-2026-4298), neither with a fix version. OPEN: suppress with a written reason, or replace `python-jose`.
- npm audit: 6 (5 moderate, 1 high). The high one is `zod` (<4.6.6, GHSA-mrhx-c7xc-m3w5); the fix is a major upgrade to zod 4 across 37 source files. OPEN: migrate, or waive with a written reason.

## Other open items
- `/api/whatif` returned 422 for `chilled_water_temp` 16 to 19.5 while the backend bound is 5 to 15; the What-if Lab offers the physics-1 range (16 to 25). Inferred from the backend log and the code; not confirmed from the 422 body.
- Linux CI: first runs found and fixed the runner image, the lock and the PyYAML dependency; the latest run result was not pasted.
