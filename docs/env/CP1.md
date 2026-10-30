# CP-1 environment: Copilot provider list (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `COPILOT_LLM_ENABLED` | `false` | Global switch (Task 24). Off = no providers, rule-based answers, no outbound call. |
| `COPILOT_LLM_PROVIDERS` | empty | Ordered, comma-separated names. Empty = one provider `default`. Names: `[a-z0-9][a-z0-9_-]{0,31}`, at most 8; bad or duplicate names are dropped. |
| `COPILOT_LLM_<NAME>_BASE_URL` | empty | OpenAI-compatible base with `/v1`. `<NAME>` is the name upper-cased, `-` becomes `_`. |
| `COPILOT_LLM_<NAME>_MODEL` | empty | Model id. |
| `COPILOT_LLM_<NAME>_API_KEY` / `_FILE` | none | Secret, read with `read_secret`. Never shared between providers. |
| `COPILOT_LLM_<NAME>_TIMEOUT_S` | global value | 0.1-120. Bad value = the global value, then 10. |
| `COPILOT_LLM_<NAME>_MAX_OUTPUT_TOKENS` | global value | 16-4000. Bad value = the global value, then 400. |
| `COPILOT_LLM_<NAME>_ENABLED` | `true` | `false` keeps the entry in the list but skips it. |
| `COPILOT_LLM_<NAME>_LOCAL` | `false` | `true` marks a provider whose data stays on this machine (data policy `local`). |
| `COPILOT_LLM_<NAME>_DATA_POLICY` | from `_LOCAL` | `local` or `cloud`. The `_LOCAL` flag decides; a cloud provider cannot claim `local`. |

The provider named `default` reads the Task 24 names (`COPILOT_LLM_BASE_URL`, `_MODEL`, `_API_KEY`, `_TIMEOUT_S`, `_MAX_OUTPUT_TOKENS`), so existing setups need no change.

Until the CP-2 router exists, only the first enabled provider with a base URL and a model is called. Log line: `copilot_llm provider=<name> model=<id> provider_request_id=<id> outcome=<word>`; never a prompt, answer, question, telemetry or key.
