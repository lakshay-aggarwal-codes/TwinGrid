# Copilot: all model providers down

Signals: answers show the badge `Rule-based explanation` with the note that the model did not answer; responses carry the
warning `llm_unavailable` (or `llm_blocked_by_policy`, `llm_busy`); the log has `llm_chain outcome=unavailable`.
**Nothing is broken for the user**: the rule-based answer is complete and its numbers come from evidence. This is a
degraded-mode runbook, not an outage runbook.

1. Read the per-attempt outcomes (provider names and outcome words only; prompts and answers are never logged):
   `docker compose logs backend --no-log-prefix --tail 300 | Select-String 'llm_chain'`
2. Local provider first: `python -m src.copilot.local`. `local_down` means start Ollama (`ollama list` to confirm);
   `local_model_missing` means `ollama pull <tag>` for the tag in `COPILOT_LLM_OLLAMA_MODEL`; `not_configured` means the
   provider name or model is missing from `.env`.
3. Cloud provider outcomes: `http_429` is the provider's rate limit (cooldown 60 s doubling to 900 s, no action needed, and do not
   add a second account of the same provider); `http_5xx`, `timeout`, `network` are the provider's or the network's problem;
   `unavailable_client_rate_limit` is our own limiter (`COPILOT_LLM_<NAME>_RPM` / `_RPD`).
4. 401 or 403 disables a provider until restart: fix the key (`docs/OPERATIONS.md`, "Replace a provider key"), then
   `docker compose restart backend`.
5. `llm_blocked_by_policy` is by design when `COPILOT_LLM_LOCAL_ONLY=true` or when the question's intent is not in
   `COPILOT_LLM_CLOUD_INTENTS`. `llm_busy` means more than `COPILOT_LLM_MAX_CONCURRENT` chains were running.
6. To stop trying models altogether: `COPILOT_LLM_ENABLED=false` and restart. Answers stay rule-based.
