# Task 24 — AI-C optional LLM phrasing adapter          Status: DONE except the live-provider test, the real-pytest run and the pytest.ini line
Base: uploaded TwinGrid-main.zip, fresh extract (Tasks 1-18 present incl. Task 14). Date: 2026-10-21
Environment: Python 3.12.3, `requests` present; **no pytest, pydantic or fastapi**.

## Acceptance
| Criterion | Status | Evidence |
|---|---|---|
| Unconfigured = rule-based | MET | `test_unconfigured_is_rule_based...`; default `answer_question(inp, ctx)` returns `rule_based`, `provider_configured False` (run directly) |
| Configured = `llm` with evidence intact | MET against a fake server | `test_a_valid_answer_becomes_llm_mode_with_evidence_intact` |
| Live provider test run | NOT RUN | no network/key here; `test_live_provider_round_trip` exists, opt-in `COPILOT_LLM_LIVE_TEST=1` |

## Tests actually run
`tests/test_copilot_llm.py`: 46 cases passed, live test deselected, under a **stand-in for pytest** (small runner I wrote for fixtures/parametrize; not pytest). Real `pytest` and the existing `tests/test_copilot_*.py` were not run.
Covers: good answer, extra number, unknown `{{E#}}`/`[E#]`/used_evidence id, HTML, entity, URL, www, markdown link, >1500, malformed placeholder, dropped "cause not determined", empty, wrong JSON shape, timeout, 429, 500/502/503, 401/404, invalid JSON, bad envelope (4), connection refused, redirect not followed, oversized reply, disabled flag, incomplete settings, no tools in the request, history never sent, numbers withheld from the model, injection text only inside the data block with the policy unchanged, obeying model rejected, logs carry model + request id and no prompt/answer/key.

## Changed files
NEW `src/copilot/llm.py`; MODIFY `src/copilot/answer.py` (import, one keyword arg, one call: `llm.enhance`), `src/copilot/__init__.py` (`MODE_LLM`), `.env.example` (append); NEW `tests/test_copilot_llm.py`, `tests/copilot_conftest_plugin.py`, `docs/env/T24.md`.

## Decisions
- `requests` (runtime dep) in a thread; `httpx` is dev-only. No lockfile edit.
- LLM is skipped (no call) when there is no evidence or the draft failed its own number check: those answers are fixed statements.
- Extra guard beyond the card: if the draft says the cause is "not determined by available evidence", the model answer must keep that phrase or it is rejected.
- Provider redirects are refused so the key cannot leave the configured host. Response capped at 256 KB.
- `live_llm` is applied by a decorator from `tests/copilot_conftest_plugin.py` because `--strict-markers` rejects `@pytest.mark.live_llm` before a `pytest_plugins` plugin registers. The plugin DESELECTS live tests unless `COPILOT_LLM_LIVE_TEST=1`, so CI needs no `-m` change. Unverified under real pytest.

## Requested cross-task changes
Integrator, optional: add `live_llm: talks to a real LLM provider; opt in with COPILOT_LLM_LIVE_TEST=1` to `pytest.ini` markers (then `@pytest.mark.live_llm` also works).

## Limitations
- **`ruff format --check` was not run** (no ruff here) and my files were hand-written, so the lint job may fail on formatting. Fix: `ruff format src/copilot/llm.py tests/test_copilot_llm.py tests/copilot_conftest_plugin.py`. `ruff check` rules E/F/I were only checked by eye (one E741 fixed).
- A literal number equal to ANY evidence value passes the check even if it belongs to another field; placeholders are the intended path. Number words ("three") are not detected.
- Qualitative claims other than the kept cause sentence are not verified; the model could say something false in words.
- Plugin deselection and the `pytest_plugins` import order are untested under real pytest.
- Not run: API route test (needs fastapi), frontend (the `llm` mode and the two warnings are new strings for Task 15's UI).

## Next unblocked
Task 25 (needs 14, 15, 24) once 15 is in.
