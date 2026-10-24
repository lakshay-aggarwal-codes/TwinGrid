# R_L3: Skip decisions and test-isolation guard

**Verdict: DONE** (owner's run, 2026-10-24). Decisions D2 = fail when absent, D3 = allow.

## State found in the tree (read, not changed in this step)
- D2: `tests/test_task20_docs_consistency.py` states that when `results.json` is absent the result-dependent tests FAIL with a clear message; a missing file no longer hides behind a skip. The only remaining `pytest.skip` there is "only meaningful for outcome C".
- D3: `tests/authz_matrix.d/T9.yaml` lists the three public access-request writes (`/api/access-requests`, `/resend-activation`, `/activate`) as allowed for a demo token; the admin routes under `/api/admin/access-requests` stay denied.
- Guard: `tests/conftest.py` has an autouse fixture (`_logging_state_must_not_leak`) that fails a test leaving `logging.root.manager.disable` or the root logger's non-pytest handlers changed.

## Evidence (pasted by the owner)
- `pytest tests/test_task20_docs_consistency.py tests/test_authz_matrix.py tests/api/test_demo_session.py -rs -q`: **247 passed, 0 skipped**.
- `ruff check .` clean; `ruff format --check .` 442 files already formatted.

## Limit
The roadmap's "done when" expects `-rs` to show only the three documented environment skips on a full run; this was a three-file run, so that check belongs to the full-suite run (L4).
