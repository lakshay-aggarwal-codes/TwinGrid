# L7 waiver: real-stack gates (R3 Task 10)

Scope: roadmap item L7 (Playwright, drills, audits). Decision: **fix the core, waive only what stayed NOT RUN.**
Evidence lives in `reports/task12/manual-*` (Playwright logs and zips) and `a11y_rerun.log`. The first collector run (`reports/task12/20261025-2324`) failed at sign-in and is superseded; it is kept unedited.

## Backend modes used

The demo stack needs one of two overlays on top of `docker-compose.demo.yml`, one pass each:

- `docker-compose.e2e.yml`: smtp mail to a sink on port 2525, public demo, trusted proxy headers (the `[smtp]` and `[api]` passes; needs `E2E_SMTP_PORT=2525` and `E2E_TRUST_PROXY=1`).
- `docker-compose.e2e-file.yml`: file mail into `E2E_OUTBOX_DIR`, public demo, `E2E_DEMO_SESSION_MINUTES` (the `[file]` and `[demo]` passes and the token-expiry drill).

## Ran, with recorded output (2026-10-26, Windows)

| Item | Result |
|---|---|
| a11y spec (48 tests: routes, drawers, admin tabs, reflow) | 48 passed |
| stale-surfaces, real-backend | 1 passed each |
| viewer-workflow `[file]` J2-J4, `[demo]` J1 and demo write routes (file overlay) | 3 passed |
| viewer-workflow `[api]` public access limits answer 429 (smtp overlay) | 1 passed |
| assistant | 2 passed, 1 failed (AI-D-3, below) |
| drills (clean run) | 3 passed, 2 failed (below) |

Journeys J1-J4 each have a passing Playwright test.

## Waived (NOT RUN, blocker named)

| Item | Why it did not run | Expiry | Sign-off |
|---|---|---|---|
| Shell drills `scripts/drill_*.sh` (db down, redis down, mail failure, history gap, large data, clean install) | The collector ran without `-IncludeDrills`; they need Git Bash and stop/start containers. | 2026-11-30 | OWNER MUST SIGN |
| Performance baseline (`perf.spec.ts`, `scripts/perf_task29.ps1`) | The collector ran without `-IncludePerf`. | 2026-11-30 | OWNER MUST SIGN |

## Not waived: ran and failed, cause not established

| Test | Last result |
|---|---|
| assistant AI-D-3 (alert explanation in the drawer equals the route) | 60 s timeout waiting for the explanation response |
| drills "refresh mid-approval" | owner sign-in as `demo_admin` did not reach "Live Twin" in 30 s |
| drills "token expiry" (`DEMO_SESSION_MINUTES=1`) | only a trace-file ENOENT error at context close was captured |
| viewer-workflow `[smtp]` (2 tests) | owner sign-in as `demo_admin` did not reach "Live Twin" in 30 s |

The owner sign-in failures are real HTTP 401 answers (the page snapshot shows "Invalid username or password" with the username filled; the UI shows that text only for a 401). The same account signed in fine from PowerShell and in other specs of the same hour. The first collector run showed the same 401 pattern. It did not reproduce on a reset demo stack for `stale-surfaces`, `real-backend`, `assistant` and the `[file]` pass. The demo database that held the audit rows was removed before they could be read, so the cause is **unexplained**. A failing test is not a waiver: these four stay Open for R3 Task 12 triage until a rerun passes or a cause is recorded.
