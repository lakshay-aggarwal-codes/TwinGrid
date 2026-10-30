# CP-2 Failover router: report

## Changed
- NEW `src/copilot/router.py`: `Router` (ordered chain, error classes, per-provider cooldown with exponential backoff and `Retry-After`, auth disable, shared time budget, rejection allowance), `Failure`, `RouteResult`, module-level `ROUTER` and `reset()`. Pure Python, injectable clock, does not import `llm.py`.
- MODIFY `src/copilot/llm.py`: `enhance` now runs the chain through the router. NEW `load_chain`. `ProviderError` gained optional `status` and `retry_after`; `_call_provider` fills them (numeric `Retry-After` only). `validate`, `SYSTEM_POLICY`, the forbidden-wording rules and `_call_provider`'s request shape are untouched. Explicit `settings=` is a chain of one, so every Task 24 test path is unchanged.
- NEW `tests/test_copilot_router.py` (28 tests): drift check, fake-clock unit tests, end-to-end tests through `enhance` with fake local HTTP servers.
- MODIFY `.env.example` (CP2 block, CP1 comment updated), NEW `docs/env/CP2.md`.

## Decisions to check
1. **Rejection rule.** "A rejected answer counts as that provider's failure and the next provider is tried once": implemented as: after the first rejection exactly one more provider is tried (whatever its outcome), then rule-based. A rejection does NOT start a cooldown (the provider answered; it is about the answer).
2. **Single-provider chain keeps no state.** No cooldown and no auth-disable when only one provider is usable. Reason: Task 24 behaviour and test isolation; the cost is that a lone dead provider is still tried (up to its timeout) on every question. Say if you want state there too.
3. **Warning code.** If any attempt was rejected and none succeeded: `llm_rejected`; otherwise `llm_unavailable`.
4. **Outer wait** is `min(budget, sum of timeouts) + 2` s, so a single provider with timeout 2 s still gives up after about 4 s as before.
5. Other 4xx (400, 404, 422) are transient, not auth: a wrong model id backs off instead of disabling the provider.

## Tested (in the build sandbox, Python 3.12, no network)
- `tests/test_copilot_router.py` 28 passed; with `test_copilot_llm.py`, `test_copilot_providers.py`, `test_copilot_answer.py`, `test_copilot_tools.py`, `test_copilot_catalogue.py`: 145 passed, 1 failed.
- The 1 failure is `test_copilot_catalogue.py::test_every_api_path_is_in_the_openapi_document`: FastAPI is not installed in the sandbox (import error in `api/main.py`). Unrelated to this change; re-run locally.
- `ruff check` and `ruff format` clean on `src/copilot/` and the new test.

## NOT tested
- `tests/test_copilot_adversarial.py` and `tests/test_copilot_api.py`: need `sqlalchemy`/`fastapi`, absent here. Run them locally. The adversarial file drives `llm._call_provider` with `ProviderError` codes and the hang case; I expect them unaffected but have not seen them pass.
- No live provider. CP-0 characterization tests do not exist yet, so "CP-0 tests unchanged" cannot be checked.
- State is per process: multi-worker deployments do not share cooldowns.
- Local-only mode and per-intent cloud policy are CP-8; Ollama health check is CP-3; client-side rate limiting is CP-4.

## Fix after first local run
`tests/test_copilot_adversarial.py::test_logs_in_llm_mode_...` counts log lines containing `copilot_llm` and expects exactly one. The new chain summary line matched that substring, so it is now `llm_chain outcome=... attempts=... total_ms=...` (no `copilot_llm` prefix). Existing test left unchanged.
