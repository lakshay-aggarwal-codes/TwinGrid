# R_TASK_9_REPORT: Viewer workflow end to end (old Task 22)

## Summary
Static work only (no network, FastAPI, Node modules, Docker or browser in my sandbox). Added the five missing cases:
mail capture over real SMTP, 375 px phone approval, outage then resend, rate-limit behaviour, demo write controls.
`e2e/viewer-workflow.spec.ts` now has 6 tests, tagged in their names so two backend modes can run in two passes
(`ACCESS_NOTIFY_BACKEND` is one setting): `[file]`, `[smtp]`, `[api]`, `[demo]`. The header of the spec lists the exact env and commands.
Backend half: `tests/api/test_task22_smtp_capture.py` (2 tests, real `smtplib` against a stdlib SMTP sink; runs in plain pytest).

Rate-limit clash with `real-backend.spec.ts` handled by: UI tests use 3 of the 5 requests/hour on the real peer IP; the
`[api]` test sends its own `X-Forwarded-For` (backend `TRUST_PROXY_HEADERS=true`, runner `E2E_TRUST_PROXY=1`) so it touches no shared window;
the outage test deliberately uses the 3 public resends/hour. Restart the backend to reset windows before a second run in the same hour.

## Acceptance checklist (journeys)
- J1 anonymous demo: `[demo]` x2 (labelled demo; every write route 403 `demo_read_only`, reads 200, `/api/copilot/ask` 200). NOT RUN.
- J2 access request: in all three UI journeys. NOT RUN.
- J3 owner decision on a phone: `[smtp]` phone test (375 px, touch, no side scroll, 44 px targets, dialog inside viewport). NOT RUN.
- J4 activation: link opened, password set, single use (`[file]`), sign-in read-only (all). NOT RUN.
- Backend half: `pytest tests/api/test_task22_smtp_capture.py -q`. NOT RUN.
- BLOCKED (needs Docker demo stack + Chromium): every Playwright test above.

## Changed files
- MODIFY `twin-stream-insight-main/e2e/viewer-workflow.spec.ts`
- CREATE `tests/api/test_task22_smtp_capture.py`
- MODIFY `api/plugins/access_requests.py` (cross-task fix, see above; outside the listed lane, needed by the journeys)
- CREATE `docs/roadmap/task-reports/R_TASK_9_REPORT.md`

## Commands run
`node --experimental-strip-types --check` on the spec: parses. `python -m py_compile` on the new test: OK. Nothing else.

## Not run
pytest, ruff, tsc, eslint, Playwright. Selectors were taken from the source (`AccessPanel.tsx`, `PendingPage.tsx`, `LoginScreen`); first real run may need small fixes.

## Decisions used
- The `[file]` activation link is now matched by recipient (the old helper took the newest mail of any visitor).
- The admin queue filter is set to "All" (the default filter hides a request once it leaves pending).
- No `skip` added. The `E2E_DEMO_DISABLED` skip on the first `[demo]` test was already there (Task 8).
- No UI "demo write control" exists (the UI does not hide write controls for demo; the server enforces), so that case is asserted on the real API with the demo session's own token.

## First real run (owner, demo stack, 2026-10-22)
`[api]` and the `[demo]` write-route test passed. `[smtp]` x2 and `[demo]` J1 failed:
- The visitor's status page said "We couldn't find this request" right after submitting. REAL BACKEND BUG: `get_db` commits after the
  response (FastAPI 0.141 runs yield-dependency exit after the response and background tasks), so a read straight after the 202 got 404, and the
  page treats a 404 as final. The same window affected approve, resend, reject and activate. Fixed with an explicit commit before responding in
  `api/plugins/access_requests.py` (6 routes); regression test `test_each_change_is_committed_before_the_response_is_sent`.
- `[demo]` J1 hit the 30 s default test timeout on the first cold load of the 3D page: now 120 s.
- The owner typed a wrong `demo_admin` password at the prompt (use the one the seed printed).

## Requested cross-task changes
- Task 8: the existing `test.skip(E2E_DEMO_DISABLED)` in the first `[demo]` test.
- Task 12: run both passes and record results.
