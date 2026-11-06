# CP-8 report: injection and privacy hardening

## What changed
- `src/copilot/sanitize.py` (new): `neutralize` (NFKC, invisible characters, links, markup, `{{ }}`, `[E#]`, `BEGIN_DATA`/`END_DATA`, chat tokens, role labels), `injection_cues`, `scrub_for_cloud`.
- `src/copilot/policy.py` (new): `COPILOT_LLM_LOCAL_ONLY`, per-intent rule `COPILOT_LLM_CLOUD_INTENTS` (default `docs_question` only), reduced cloud request + fail-closed leak check, concurrency gate `COPILOT_LLM_MAX_CONCURRENT` (default 4).
- `llm.py`: applies policy; cloud providers get the reduced request, local ones the full one; new warnings `llm_blocked_by_policy`, `llm_busy`. `answer.py`/`docs_answer.py`: passages and headings neutralised; passages with cues are held back (`docs_passage_withheld`) or, if all have cues, quoted as data with no model (`docs_passage_flagged`). Route passes the user name only so it can be removed from cloud requests.
- Decisions applied by default (you did not answer): cloud intents = docs questions only; alert explanations and live status are local-or-rule-based unless listed.

## Behaviour changes to know
- Without `COPILOT_LLM_CLOUD_INTENTS`, a cloud provider no longer phrases alert/signal/model answers. `tests/conftest.py` now sets `*` for the whole suite so older tests keep their meaning; `test_copilot_policy.py` removes it.
- `test_copilot_rag_answer.py`: two CP-7 tests changed on purpose (poisoned passage is now withheld, not quoted defanged).
- New warning codes show raw in the frontend until CP-10 adds texts.

## Tested here (shim, not real pytest)
This container has no pytest or pydantic, so I ran the tests with a small stand-in runner. 338 passed, 1 failed (`test_the_response_schema_accepts...`, needs real pydantic; it also fails on the untouched zip under the stand-in). Covered: new `test_copilot_policy.py` (45), `test_copilot_hardening.py` (61), and the existing llm, router, presets, local, answer, rag_answer tests.

## Not run / open
- Real pytest, `test_copilot_api.py`, `test_copilot_adversarial.py`, `tests/characterization/copilot/*`, ruff, frontend. The adversarial and characterization tests use non-local fake providers with alert/signal questions: they rely on the new suite-wide `*` fixture.
- Rate limit review: `ask` still shares the `state` class (30/min per user). Not changed; the concurrency cap protects workers, the CP-4 limiter protects provider quotas.
- Lexical guards only: paraphrased or non-English injections and look-alike letters are not detected.
