# R-Task 10: Assistant fake-LLM suite
Status: **PARTIAL** (tests written and logic-checked offline; real `pytest`, the 5 HTTP cases and `ruff` NOT run)
Base: uploaded `TwinGrid-main.zip` (2026-10-21), Python 3.12.3 here, **no pytest, fastapi, pydantic, ruff or network**.

## Summary
The adversarial suite now runs invariants 1-4, 8 and 9 with the optional model switched on, against a **test-only fake provider** that replaces `src.copilot.llm._call_provider`. The real validator, answer builder and route still decide what the client sees. The fake returns invented numbers, jailbreak text, malformed replies, provider errors, a crash, and a provider that never answers.

**Important finding (not a test problem):** the validator rejects bad numbers, markup, links and ghost placeholders, but not bad *words*. Nine replies are accepted as mode `llm` today although they break an invariant (named cause, "I have acknowledged...", "calibrated to a real facility", "production-ready", "saves energy", "I have granted you admin", stale signal called "normal and live" / "healthy", a number spelled out as "ninety-nine percent"). I did not hide this and did not fix it (it is `src/copilot/llm.py`, outside this task). They are pinned as one strict xfail group, see below.

## Acceptance checklist
| Criterion | Status | Evidence |
|---|---|---|
| Fake provider, test-only and labelled | MET | `FakeLlm` + `fake_llm` fixture in `tests/copilot_conftest_plugin.py`, header says TEST-ONLY |
| Returns invented numbers, jailbroken text, timeouts | MET | `llm_replies.json` (8 / 11 / 9 replies) plus `fail()`, `crash()`, `hang()` |
| Invented number from the fake LLM rejected in a test, **with the warning asserted** | MET (logic run) | `test_an_invented_number_from_the_fake_model_is_rejected_with_the_warning` asserts `llm_rejected`, absence of `llm_unavailable`, answer/evidence/links byte-equal to rule-based. 24 cases pass in my stand-in runner; with the number check disabled all 24 fail (mutation run) |
| Final answer only contains server-resolved numbers, falls back to rule-based | MET (logic run) | `assert_fell_back` + `assert_grounded` on every case, and a positive control proves `llm` mode is reachable |
| Invariant 8 asserts `llm_unavailable` / `llm_rejected` | MET (logic run) | new tests, and the old tautological assertion in `test_a_configured_but_unreachable_provider...` replaced (see below) |
| `pytest tests/test_copilot_llm.py tests/test_copilot_adversarial.py -q` passes | **NOT RUN** | no pytest here |

## Tests added (all in `tests/test_copilot_adversarial.py`, section 10)
Runnable without a database (checked offline, see below):
- positive control x3 contexts (alert / model / stale signal): a faithful reply reaches `llm`, evidence and links unchanged
- invented numbers: 8 forms x 3 contexts = 24 (percent, `%`, `1,000`, full-width and Arabic-Indic digits, `1e6`, another alert id, a plausible literal)
- jailbroken/malformed replies: 11 (script tag, entity, URL, bare www, markdown link, `javascript:`, ghost placeholder and marker, broken placeholder, control char, over-length)
- broken format: 6 (not JSON, array, wrong types, ghost `used_evidence`, empty)
- provider failures: 8 codes + 1 unexpected crash + 1 hang (real 2.1 s adapter timeout)
- obedient model + hostile alert text: 6 payloads (prompt hygiene: system policy unchanged, roles exactly system+user, text only in the data block; outcome refused or adds no evidence/link/markup)
- **strict xfail**, 9 cases: forbidden wording accepted (finding above)

Written, **not run** (need fastapi + a database): 5 HTTP cases: faithful reply served as `llm`; invented number rejected with warning over HTTP; timeout is a normal answer; 429 happens before the fake is asked (one model call per 200); logs in `llm` mode hold model + outcome but no prompt, answer, question, alert text or API key.

Changed existing test: `test_a_configured_but_unreachable_provider_never_breaks...` had an assertion that is always true. It now asserts `llm_unavailable` present, `llm_rejected` absent, and `limits == {"provider_configured": bool(base_url)}`. I ran those four configurations through the real adapter here: all give `llm_unavailable`; `limits` is True for three and False for the empty URL.

## Changed files
- MODIFY `tests/test_copilot_adversarial.py` (docstring, 3 imports, `pytest_plugins`, `MODES` comment, one test tightened, section 10 added; the other ~800 lines untouched)
- MODIFY `tests/copilot_conftest_plugin.py` (adds `FakeLlm`, `fake_llm`, `reply`, `data_block`, `evidence_id`; Task 24 live-test code unchanged)
- CREATE `tests/fixtures/copilot_adversarial/llm_replies.json`
- CREATE `docs/roadmap/task-reports/R_TASK_10_REPORT.md`, `R_TASK_10_adversarial.patch`

## Commands run
- Offline stand-in runner (NOT pytest; stub `pytest` module, executes the real test bodies and the real `src.copilot` code): **60 passed, 0 failed, 9 xfailed as expected, 0 unexpected passes**. It caught a bug in my own positive-control test (eager dict evaluation), fixed before delivery.
- Mutation run (number check disabled): the 24 invented-number tests fail, so they bite.
- `ast.parse` on every Python file.

## Not run
`pytest` (any), the 5 HTTP cases, `ruff check`, `ruff format --check` (import order and wrapping done by eye; run `ruff format tests; ruff check --fix tests`). Under real pytest unverified: plugin double-registration via `pytest_plugins` in two modules, and `async` test collection of the new cases (the suite already uses auto mode).

## Decisions used
- Fake replaces `_call_provider`, not an HTTP server (Task 24's own file already covers the wire); still goes through the real validator.
- Placeholders are looked up by evidence field (`evidence_id`), never hard-coded, so a reply cannot pass for the wrong reason.
- Known gaps are one strict xfail group with the reason naming `src/copilot/llm.py`. Per Task 8 it points at an owner; it has no roadmap number yet, so **add the llm.py fix as a task** (or tell me to).

## Requested cross-task changes
1. **`src/copilot/llm.py` `validate()`** (new work item): reject typed claim words outside `{{E#}}` placeholders (the `_FORBIDDEN_CLAIMS` patterns, affirmative normal/live/healthy, number words). When done, the strict xfail starts failing "unexpected pass"; delete its marker.
2. **Apply as a patch, not a file copy.** Tasks 1, 2, 3 also edit `test_copilot_adversarial.py` (removing xfails). Copying my full file over theirs would restore those xfails. Use `R_TASK_10_adversarial.patch`; it applies cleanly to the uploaded base (dry run done) and touches different regions.
3. Optional: `pytest.ini` marker line for `live_llm` (Task 24 note), unchanged.
4. Observation: when the provider call raises something unexpected, `limits.provider_configured` stays `False` even though a provider is configured (warning is still `llm_unavailable`). Minor, not asserted.

Verdict: **PARTIAL**. Counts seen: 60 passed / 9 xfailed / 0 failed under the stand-in runner only; real pytest 0 runs.
