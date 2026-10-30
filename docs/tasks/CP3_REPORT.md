# CP-3 Local Llama (Ollama): report

## Changed
- NEW `src/copilot/local.py`: Ollama preset, health check (`/api/tags`, 1 s, cached 30 s up / 15 s down), local timeout, `python -m src.copilot.local`.
- MODIFY `src/copilot/llm.py` (CP-2 version): `load_settings`/`load_chain` apply the preset; `enhance` lengthens the timeout of local providers and runs the health check inside the attempt (down or model missing -> `Failure(transient, unavailable_local_*)`, so the router's cooldown applies too). Validation, rejection rules and request shape untouched.
- NEW `tests/test_copilot_local.py` (36 tests, fake HTTP only, one `live_llm` test deselected by default), `docs/copilot/LOCAL_LLM.md`, `docs/env/CP3.md`, `docker-compose.ollama.yml` (profile `ollama`).

## Decisions
1. Preset lives in `local.py`, not `providers.py` (CP-1 file was not available to me); it works by filling default env values before CP-1 parsing.
2. `LOCAL` defaults to true only for loopback / host.docker.internal / `ollama`; a remote Ollama host is never auto-flagged local.
3. Local timeout applies only to a local provider still on the default timeout; an explicit per-provider timeout wins.
4. `COPILOT_LLM_BUDGET_S` is NOT auto-raised: set it to at least the local timeout (documented).
5. `.env.example` is not shipped (drift risk); the block is in `docs/env/CP3.md`.

## Tested (build sandbox, Python 3.12, no network, no pytest, no ruff)
- Ran with a small stand-in runner, not real pytest: `test_copilot_local.py` 36 passed; `test_copilot_router.py` 28 passed; `test_copilot_llm.py` 55 passed, 1 not runnable in the runner (`tmp_path`).
- `providers.py` was a reconstruction from `llm.py`'s use, NOT your CP-1 file. Run locally to confirm.

## NOT tested
- Real pytest, `ruff check/format`, the `live_llm` test, a real Ollama, the Docker overlay, `api/` tests.
- Startup health check is not wired into API startup (not seen); the first question probes (<= ~1 s) and the result is cached. `python -m src.copilot.local` is the on-demand check.
