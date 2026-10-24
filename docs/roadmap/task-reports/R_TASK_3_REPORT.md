# R_TASK_3_REPORT: Demo session vs assistant

Status (L4, 2026-10-24): **DONE**. `tests\api\test_demo_session.py` passes in the owner's full run (5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed).

## Summary
Static audit of `TwinGrid-main.zip`. `api/demo_guard.py` already lists `/api/copilot/ask` in `ALLOWED_DEMO_WRITES`, so the guard is not broken and is unchanged. The strict xfail `test_the_demo_session_may_ask_and_gets_what_a_viewer_gets` was stale: it would XPASS and fail the run under `strict=True`. It is removed. New tests lock "demo can ask, demo cannot write".

## Acceptance checklist
- Xfail for demo assistant access removed: MET (file edit; not run).
- Demo token gets 200 from `/api/copilot/ask`: test added, NOT RUN.
- Demo token gets 403 `demo_read_only` on every guarded write route in the matrix (T13 `demo: 403` rows plus the three T9 public access-request routes, which have no `demo` column): test added; first run 146 passed, 1 failed (T9 rows missing from my first version), fixed.
- Matrix-denied set equals guarded write routes in `app.openapi()`: test fixed after your run, NOT re-run.
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

## Run by owner (first version)
`pytest tests/api/test_demo_session.py tests/test_copilot_adversarial.py -q`: 146 passed, 1 failed, 3 xfailed (Tasks 1, 2 and one more pinned defect). `ruff check .` and `ruff format --check .` passed on the first version.

## Requested cross-task changes
Task 6 (owns `tests/authz_matrix.d/*.yaml`): add `demo: 403` to the three T9 rows `POST /api/access-requests`, `/activate`, `/resend-activation`. The test already treats them as denied.

## L4 update (2026-10-24): run evidence and one change of direction
- `tests\api\test_demo_session.py` shows only passes in `C:\twlogs\pytest_full_final.txt` (57 tests, which includes the L3 additions). The strict xfail for demo assistant access is gone and `tests\test_copilot_adversarial.py` has only the 9 validator xfails.
- The cross-task request above ("add `demo: 403` to the three T9 access-request rows") is **superseded by L3 decision D3 (allow)**: those three public POSTs are now in `ALLOWED_DEMO_WRITES` (`api/demo_guard.py`), and `tests\test_authz_matrix.py` passes with that.
