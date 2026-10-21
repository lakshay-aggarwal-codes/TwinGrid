# Task 14 — AI-A Copilot backend, evidence tools, rule-based answers          Status: PARTIAL
Base: TwinGrid-main.zip as uploaded 2026-10-20   Date: 2026-10-21
Environment: Python 3.12.3; NO pytest, fastapi, pydantic or network. Pure-Python parts were run with a home-made pytest
stand-in. The plugin, schemas and HTTP tests were NOT executed.

## Summary
`POST /api/copilot/ask` answers from templates filled with cited evidence; no language model, `mode == "rule_based"`.
Numbers and names appear only as `[E#]` markers. Missing or stale data becomes `unknowns`; the cause of an alert is always
"not determined by available evidence".

## Acceptance checklist
- Journey J5 with no provider, `mode == "rule_based"` -> built, not run (needs fastapi): `tests/test_copilot_api.py`.
- Known-value fixture -> evidence equals fixture exactly; every number in the answer is backed; stale/missing -> unknowns, never "normal"; unknown cause stays unknown; injection quoted as data with the answer unchanged; no write tools; catalogue UI paths; simulated origin -> run (stand-in): 43 pass.
- Oversize input 422, history bounds, 401, rate limit, no prompt logging, OpenAPI contract -> written, NOT run.
- Catalogue `api_path`s exist in OpenAPI -> written, NOT run (needs `app.openapi()`); I checked each path by reading the route decorators.

## Changed files (all new)
api/plugins/copilot.py; src/copilot/{__init__,schemas,evidence,tools,answer,catalogue,signal_adapter}.py; docs/copilot/capabilities.json;
tests/test_copilot_{answer,tools,catalogue,api}.py; tests/fixtures/copilot/*; tests/fixtures/__init__.py; tests/authz_matrix.d/T14.yaml; this report.

## Commands run (stand-in runner, NOT real pytest)
test_copilot_answer / _tools / _catalogue: 43 pass, 1 fail (`test_every_api_path_is_in_the_openapi_document`: fastapi missing).

## Not run / blocked
Real pytest, `ruff check` and `ruff format` (my lines were not auto-formatted: run `ruff format` on the new files), every test that imports fastapi or pydantic, `tests/test_authz_matrix.py`, `test_task18_*`.

## Decisions and defaults used
- Layering: `src/copilot` is pure Python and receives loaders; the plugin supplies them by calling `explainability.alert_explanation` / `model_passport` (the routes' own functions) and `data_repository.get_alert`. No rule maths is copied.
- Errors use the application's problem body. A body-validation failure is therefore `urn:twingrid:error:validation_error`, not `invalid_request`; status codes are as in 8.4.
- Rate limit: existing `state` class (30/min); a dedicated `copilot` scope would need a change to `api/config.py` (not owned).
- No threshold rules exist in the repo (Task 16 owns them). `get_threshold_rule` returns only the simulator safety envelope's critical bounds (origin `assumed`); every status is `unknown` / `rule_unavailable` until `src/signal_state.py` exists.
- Stored alert evidence has freshness `static`; live samples are fresh/stale against an assumed 120 s limit.
- Alert link is `/alerts` (there is no `/alerts/:id` route in the UI); say if Task 15 adds one.
- History is validated and ignored (answers cannot be steered by it). `docs/env/T14.md` is not written: there are no new environment variables.
- API tests live at `tests/test_copilot_api.py` (so the verify glob finds them) and re-export the `tests/api` fixtures.
- The authz fragment expects 422 for authorised roles because the probe sends no body; adjust to the Task 3 harness if it sends one.

## Requested cross-task changes
Task 3 harness: confirm the fragment schema. Task 16: `src/signal_state.py` with `evaluate(value, observed_at, now, rule, stale_after_s, connected)` and `SignalRule(rule_id, unit, warn_low, warn_high, crit_low, crit_high)`, which is what the adapter calls.

## New limitations or risks
Unverified under real FastAPI/pydantic: schema `Literal[...]` built from tuples, the SQLAlchemy signal query, fixture re-export in the API tests.

## Next tasks unblocked
Task 15 (UI) against the real contract; Task 24 (LLM phrasing) can wrap `answer_question` without changing evidence.
