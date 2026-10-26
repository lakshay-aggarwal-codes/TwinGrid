# R3 Task 10: waiver decision

- L2: closed. `docs/roadmap/task-reports/R_L2_REPORT.md` says DONE (835 passed, 1 skipped, ruff clean, TG-A-05 resolved by removal).
- L7: decision recorded in `docs/frontend/waivers/L7_real_stack_gates.md` (fix core, waive only NOT RUN items).
- Added `docker-compose.e2e.yml`: backend env overlay (file mail, public demo, demo session minutes) used for the J1-J4 and drill passes.
- Evidence: the pasted Playwright summaries of 2026-10-26 (a11y 48 passed; viewer-workflow file+demo 3 passed). Unexplained: the 401 sign-ins of the first collector run did not reproduce on a reset demo stack.
- Open: AI-D-3, refresh drill, token-expiry drill (see the waiver file).
