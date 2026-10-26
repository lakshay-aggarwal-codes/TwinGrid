# R3 Task 10: waiver decision

- L2: closed. `docs/roadmap/task-reports/R_L2_REPORT.md` says DONE (835 passed, 1 skipped, ruff clean, TG-A-05 resolved by removal).
- L7: decision recorded in `docs/frontend/waivers/L7_real_stack_gates.md`: fix the core, waive only what stayed NOT RUN (shell drills, perf).
- Overlays: `docker-compose.e2e.yml` is the original smtp overlay (restored; an earlier commit of this task overwrote it by mistake), `docker-compose.e2e-file.yml` is the file-mail overlay.
- Evidence: pasted Playwright summaries of 2026-10-26: a11y 48 passed, viewer-workflow file+demo 3 passed, `[api]` 1 passed.
- Open, unexplained: owner sign-in 401s (4 tests) and AI-D-3. The audit rows that could explain them were lost when the demo stack was removed.
