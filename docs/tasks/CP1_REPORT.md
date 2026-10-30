# CP-1 Provider abstraction: report

## Changed
- NEW `src/copilot/providers.py`: `ProviderConfig` (name, base_url, model, key secret name, api_key, timeout, max output tokens, enabled, local, data policy), `load_providers`, `active_providers`, `parse_names`.
- MODIFY `src/copilot/llm.py`: settings now come from the provider layer (`load_settings` returns the first usable provider as `LlmSettings`; `LlmSettings` gained `name` and `local`, defaults unchanged); log line gained `provider=<name>`. `validate`, `SYSTEM_POLICY`, the forbidden-wording rules, `_call_provider` and `enhance` are untouched.
- NEW `tests/test_copilot_providers.py` (config parsing, bad values, disabled providers, key isolation, data-policy rule, legacy equality).
- MODIFY `.env.example` (CP1 block), NEW `docs/env/CP1.md`.

## Assumed files (the drift test checks the llm.py seams)
`src/copilot/llm.py`, `src/copilot/answer.py`, `api/plugins/copilot.py`, `api/secrets.py`, `tests/copilot_conftest_plugin.py`, `tests/test_copilot_llm.py`, `tests/test_copilot_adversarial.py`.

## Not done / not verified
- CP-0 was not in the upload (`tests/characterization/copilot` and `docs/copilot/CURRENT_STATE.md` do not exist), so "CP-0 tests still pass" could not be checked. The existing Task 24 tests are the regression bar.
- pytest, FastAPI and ruff are not installed in the build sandbox: the new tests were run with a minimal stand-in runner only; `tests/test_copilot_llm.py` and `tests/test_copilot_adversarial.py` were NOT run. Run them locally.
- Failover is not implemented (CP-2). With several providers listed, only the first usable one is used.
- Log format changed (added `provider=`). The existing log tests match on substrings and should be unaffected.
