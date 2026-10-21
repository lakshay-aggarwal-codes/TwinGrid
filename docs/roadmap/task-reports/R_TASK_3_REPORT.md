# R_TASK_3_REPORT: Demo session vs assistant

## Summary
Static audit of `TwinGrid-main.zip`. `api/demo_guard.py` already lists `/api/copilot/ask` in `ALLOWED_DEMO_WRITES`, so the guard is not broken and is unchanged. The strict xfail `test_the_demo_session_may_ask_and_gets_what_a_viewer_gets` was stale: it would XPASS and fail the run under `strict=True`. It is removed. New tests lock "demo can ask, demo cannot write".

## Acceptance checklist
- Xfail for demo assistant access removed: MET (file edit; not run).
- Demo token gets 200 from `/api/copilot/ask`: test added, NOT RUN.
- Demo token gets 403 `demo_read_only` on every write route in `tests/authz_matrix.d/T13.yaml` (`demo: 403` rows): test added, NOT RUN.
- T13.yaml `demo: 403` rows equal the guarded write routes in `app.openapi()`: test added, NOT RUN.
- Ask route has no write tool: tools registry has no write name and the route plugin has no write call (static test added, NOT RUN); a demo ask leaves every table's row count unchanged (test added, NOT RUN).
- The two other `xfail` markers left in `test_copilot_adversarial.py` belong to Tasks 1 and 2.

## Changed files
- MODIFY `tests/test_copilot_adversarial.py` (xfail removed; demo assertion tightened from `in (200, 403)` to `== 200`)
- MODIFY `tests/api/test_demo_session.py` (5 new tests)
- CREATE `docs/roadmap/task-reports/R_TASK_3_REPORT.md`

## Commands run
`python -m py_compile` on both test files: OK. Line-length check (120): clean.

## Not run
No FastAPI, httpx, SQLAlchemy or ruff in my sandbox, so no pytest, ruff check or ruff format. Tests-first (rule 5) was not shown failing, because the fix already existed in the guard. Run the commands in the PowerShell block.

## Decisions used
Guard unchanged, since it is correct. Tightened the 200/403 assertion, because accepting 403 is what hid the defect.

## Requested cross-task changes
None.
