# R-Task 1: Copilot signal lookup and alert-id parsing

Status: **DONE** (backend; no frontend change, no migration)

## Summary
Two defects in `api/plugins/copilot.py` are fixed and each has tests:
1. `load_signal` filtered `TelemetrySample.quality == "good"`, a value the schema forbids (`ck_telemetry_quality`: `'ok'` or `'invalid'`), so a stored live sample was never found. It now uses `"ok"` (constant `_USABLE_QUALITY`).
2. `alert_id.isdigit()` is True for characters like `"²"` and `"①"`, which `int()` rejects, so the endpoint returned HTTP 500. It now uses `re.fullmatch(r"[0-9]{1,18}", ...)` (ASCII digits only), so such ids return the normal 404 "Alert not found". This also refuses full-width digits, signs, underscores and spaces, which `int()` would have accepted.

## Acceptance checklist
| Criterion | Result | Evidence |
|---|---|---|
| Both previously xfailed tests pass as normal tests | MET | the two `xfail(strict=True)` markers for these defects were removed; both tests failed on the unfixed code (HTTP 500 / no evidence) and pass now |
| No xfail remains for these two defects | MET | `grep -n "load_signal filters\|isdigit" tests/test_copilot_adversarial.py` finds nothing |
| Invalid / non-ok samples never used | MET | new test: a newer `invalid` sample (999.0) does not replace or hide the older `ok` one |
| Stricter id check does not break real ids | MET | new positive-control test with a real alert |

## Changed files
- MODIFY `api/plugins/copilot.py`: the two fixes above (adds `import re`, `_ALERT_ID`, `_USABLE_QUALITY`)
- MODIFY `tests/test_copilot_adversarial.py`: removed the two Task-1 xfail markers; added 4 test functions (11 cases): newest-ok-over-newer-invalid, fresh ok sample is `fresh`, 8 odd alert ids, plain ASCII alert id still works
- CREATE `docs/roadmap/task-reports/R_TASK_1_REPORT.md`

## Commands run (Python 3.12.3, no TensorFlow/torch/Postgres)
| Command | Before (baseline) | After |
|---|---|---|
| `pytest tests/test_copilot_adversarial.py tests/test_copilot_tools.py tests/test_copilot_answer.py` | 1 failed, 129 passed, 3 xfailed | see next row |
| same four copilot files + `test_copilot_llm.py` | n/a | 1 failed, 188 passed, 1 deselected (live LLM), 1 xfailed |
| `pytest tests -m "not postgres" -k "copilot or demo_session" --continue-on-collection-errors` | 1 failed, 253 passed, 2 skipped, 3 xfailed, 5 collection errors | 1 failed, 266 passed, 2 skipped, 1 xfailed, 5 collection errors |
| `ruff check` and `ruff format --check` on the 2 changed files | n/a | clean |

Net: +13 passed, -2 xfailed, 0 new failures.

## Pre-existing failures observed (not caused by this task, not fixed here)
- `test_the_demo_session_may_ask_and_gets_what_a_viewer_gets` **fails on baseline** with a strict XPASS: Task 27 already added `/api/copilot/ask` to the demo allow-list, so the xfail marker is stale. **Belongs to R-Task 3:** remove that marker. This is also why 1 test is still red.
- 1 xfail remains: the future-dated-sample defect (`src/signal_state.evaluate`), **R-Task 2**.
- 5 collection errors, same set before and after: `test_artifact_integrity`, `test_authz_matrix`, `test_t27_env_v2`, `test_task10_governance`, `test_task8_release`. For `test_authz_matrix` the error in my venv was `ModuleNotFoundError: No module named 'yaml'`: **PyYAML is not listed in `requirements*.txt` or `requirements.lock`**, yet `tests/authz_matrix.py` needs it. **Useful for R-Task 6** (declare it in `requirements-dev.txt`, then re-lock if needed). I did not check the other four.

## Not run / blocked
Postgres suite, TensorFlow tests, frontend gates (not touched), full `pytest tests` (only the copilot-related subset above). Full-suite command: `pytest tests -m "not postgres" -rs -q`.

## Decisions and defaults used
- Id rule: ASCII digits, 1 to 18 characters. Same 18-character cap as before. Ids longer than the schema's limit are still refused earlier with a 422 (not tested here, already covered by the hostile-id tests).
- I touched only the two xfail markers that belong to this task, not the demo or future-dated ones.

## Requested cross-task changes
- R-Task 3: delete the stale xfail on `test_the_demo_session_may_ask_and_gets_what_a_viewer_gets`.
- R-Task 6: declare PyYAML.

## New limitations or risks
None known. Behaviour change: ids with signs, spaces or underscores that `int()` used to accept now return 404 instead of looking up an alert.

## L4 update (2026-10-24): full run
Owner ran `pytest tests -m "not postgres" -rsx -q` (`C:\twlogs\pytest_full_final.txt`): 5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed. The `test_signal_state`, `test_copilot_*` and `api/test_*` files this task touched show no failure. The 5 collection errors listed above are gone (all of those files ran). The 9 xfails are all the open validator defect (`test_a_fake_reply_whose_only_fault_is_forbidden_wording_is_rejected`, fix tracked as L1); none belongs to this task.
