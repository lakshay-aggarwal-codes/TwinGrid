# L7 waiver: real-stack gates (R3 Task 10)

Scope: roadmap item L7 (Playwright, drills, audits). Decision: **fix the core, waive only what stayed NOT RUN.**
Evidence lives in `reports/task12/manual-*` (the Playwright logs and zips) and `a11y_rerun.log`. The first collector run (`reports/task12/20261025-2324`) failed at sign-in for environment reasons and is superseded; it is kept unedited.

## Ran, with recorded output (2026-10-26, Windows, demo stack)

| Item | Result |
|---|---|
| a11y spec (48 tests, routes, drawers, admin tabs, reflow) | 48 passed |
| stale-surfaces, real-backend | 1 passed each |
| viewer-workflow `[file]` J2-J4 and `[demo]` J1 plus demo write routes (with `docker-compose.e2e.yml`) | 3 passed |
| assistant | 2 passed, 1 failed (AI-D-3, see below) |
| drills | 3 passed in the clean run |

Journeys J1-J4 each have a passing Playwright test.

## Waived (NOT RUN, blocker named)

| Item | Why it did not run | Expiry | Sign-off |
|---|---|---|---|
| viewer-workflow `[smtp]` (2 tests) | Needs the backend in smtp mode (`ACCESS_NOTIFY_BACKEND=smtp`, host reachable from the container) and `E2E_SMTP_PORT`. Not set up. The `[file]` pass covers the same journey except real SMTP transport. | 2026-11-30 | OWNER MUST SIGN |
| Shell drills `scripts/drill_*.sh` (db down, redis down, mail failure, history gap, large data, clean install) | The collector ran without `-IncludeDrills`; they need Git Bash and stop/start containers. | 2026-11-30 | OWNER MUST SIGN |
| Performance baseline (`perf.spec.ts`, `scripts/perf_task29.ps1`) | The collector ran without `-IncludePerf`. | 2026-11-30 | OWNER MUST SIGN |

## Not waived: ran and failed, cause not established

| Test | Last result | Owner of the next step |
|---|---|---|
| assistant AI-D-3 (alert explanation in the drawer equals the route) | 60 s timeout waiting for the explanation response | R3 Task 12 triage |
| drills "refresh mid-approval" | owner sign-in did not reach the "Live Twin" heading in 30 s; Playwright trace-file ENOENT errors in the same log | R3 Task 12 triage |
| drills "token expiry" (with `DEMO_SESSION_MINUTES=1`) | only a trace-file ENOENT error at context close was captured; the test body result is unknown | R3 Task 12 triage |

A failing test is not a waiver. These three stay Open until a rerun passes or a cause is recorded.
