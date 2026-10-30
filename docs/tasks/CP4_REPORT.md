# CP-4 Free-tier provider profiles and rate limiter: report

## Changed
- NEW `src/copilot/presets.py` (gemini, groq, openrouter, github: base URL, conservative rpm/rpd, docs link; env overrides `COPILOT_LLM_<NAME>_RPM/_RPD`).
- NEW `src/copilot/limiter.py` (thread-safe sliding 60 s / 24 h windows per provider key; refused requests not recorded).
- MODIFY `src/copilot/llm.py` (CP-3 version): presets applied next to the Ollama preset; limiter checked inside each attempt (outcome `unavailable_client_rate_limit`, router quota cooldown with the wait as `Retry-After`).
- NEW `tests/test_copilot_presets.py` (34 tests, fake HTTP only), `docs/copilot/PROVIDERS.md`.

## Decisions
1. Presets live in `presets.py`, not `providers.py` (CP-1 file not available to me): they fill default env values before CP-1 parsing.
2. Models are never defaulted. Default limits are conservative; Gemini and GitHub numbers are placeholders (not verified).
3. Limits are per provider name, in-process, rolling windows (not provider-side calendar resets).
4. No per-provider headers: all four take Bearer on the same request shape. 402 stays "transient", 403 stays "auth" (CP-2 rules).
5. `.env.example` not shipped; the setup block is in `PROVIDERS.md`.

## Tested (build sandbox, Python 3.12, no network, no pytest, no ruff)
- Small stand-in runner, not real pytest: `test_copilot_presets.py` 34 passed; `test_copilot_local.py` 36, `test_copilot_router.py` 28 passed; `test_copilot_llm.py` 55 passed, 1 not runnable in the runner (`tmp_path`).
- `providers.py` was a reconstruction from `llm.py`'s use, not your CP-1 file.

## NOT tested
- Real pytest, `ruff`, any live provider, provider data-use terms (all "verify before use"), per-model Gemini/GitHub limits, multi-worker behaviour.
- Provider quirks are from documentation only; none were hit live.
