# R3 Tasks 5 to 10: evidence from your tree

One combined file with a new name, so it cannot overwrite a per-task report already committed in the repo. No code change this round: the fixes were already in the tree.

Evidence run (your machine, branch `wip/bc10-run-contract`, `c04d895`):
`pytest -k "demo_session_may_ask or newest_ok_sample or unicode_digit_alert_id or oddly_formed_alert_ids or plain_ascii_alert_id or future_dated_reading" tests/test_copilot_adversarial.py tests/test_signal_state.py` gave **47 passed, 276 deselected, 0 failed** (4.9 s). The pasted tail showed only the future-dated cases; the other test names were not displayed.

| # | Task | Status | What the evidence shows |
| --- | --- | --- | --- |
| 5 | Copilot in the demo | **Open, one check left** | `api/demo_guard.py:36` allows `/api/copilot/ask`. The test `test_the_demo_session_may_ask_and_gets_what_a_viewer_gets` (read in the repo, not shown in your output) asserts the demo gets 200, equals the viewer's answer, and the database snapshot is unchanged. No `db.add`, `commit` or audit write appears in `api/plugins/copilot.py` or `src/copilot/`. |
| 6 | Copilot signal lookup | **Open, one check left** | `api/plugins/copilot.py:42` sets `_USABLE_QUALITY = "ok"` and line 69 filters on it. The test `test_the_newest_ok_sample_is_used_and_a_newer_invalid_one_is_ignored` exists in the repo; it is in the 47 passes but its name was not displayed. |
| 7 | Alert id crash | **Open, one check left** | Alert ids are ASCII digits only (`api/plugins/copilot.py:37`). Tests for superscript two and other odd ids, expecting 404 and never 500, exist in the repo and sit inside the 47 passes. Names not displayed. |
| 8 | Future-dated samples | **Done** | `test_a_future_dated_reading_is_unknown_with_no_number_never_normal_or_an_alarm` passed for every case shown (ahead by 3600 s and 31536000 s, values from -1e9 to 1e9). `src/signal_state.py` marks it `unknown` with reason `future`. |
| 9 | Authz matrix | **Done** | `tests/test_authz_matrix.py`: **183 passed**. `tests/authz_matrix.d/T13.yaml` is in the loader's overlay format; its last commit is `0d38e3c`, "Task 6: Authorization matrix actually enforced". |
| 10 | Waiver decision | **Done** | `docs/frontend/waivers/L7_real_stack_gates.md` states the decision: "fix the core, waive only what stayed NOT RUN" (R3 Task 10). `R_L2_REPORT.md` reads "Verdict: DONE (owner's run, 2026-10-24). Decision D1 = retire." |

## To close 5, 6 and 7

The test names have to be shown. Run:

```powershell
python -m pytest -p no:cacheprovider --collect-only -q -k "demo_session_may_ask or newest_ok_sample or unicode_digit_alert_id or oddly_formed_alert_ids or plain_ascii_alert_id" tests/test_copilot_adversarial.py | Select-String "::"
```

All of the named tests are in the 47 passes, so once the names show, the three tasks close on their pasted output.

## Not verified

- The tail of the waiver. It says assistant AI-D-3 and two drills failed "below"; I read only the first 22 lines, so whether those failures are fixed or waived is not confirmed. Task 10's "Done when" (the L7 decision is in `docs/frontend/waivers/`) is met by the header.
- `/api/copilot/ask` was not called live as a demo token.
- That no other R3 report for these tasks already exists in the repo under the per-task names.
