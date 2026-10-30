# CP-3 environment: local Llama (Ollama)

| Variable | Default | Meaning |
|---|---|---|
| `COPILOT_LLM_PROVIDERS` containing `ollama` | - | Enables the Ollama preset. |
| `COPILOT_LLM_OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Host/Docker variant: `http://host.docker.internal:11434/v1`. |
| `COPILOT_LLM_OLLAMA_MODEL` | none (required) | An installed tag, e.g. `llama3.2:3b`. Not defaulted. |
| `COPILOT_LLM_OLLAMA_LOCAL` | `true` for localhost, 127.0.0.1, ::1, host.docker.internal, `ollama`; unset otherwise | `true` means no data leaves this machine. |
| `COPILOT_LLM_LOCAL_TIMEOUT_S` | `30` (1-300) | Timeout for local providers that keep the default 10 s timeout. |

Health check: `GET <root>/api/tags`, 1 s timeout, model must be listed; result cached 30 s (up) / 15 s (down).
Block to append to `.env.example`:

```
# ---- CP3 BEGIN: local Llama via Ollama (docs/copilot/LOCAL_LLM.md, docs/env/CP3.md) ----
# Put "ollama" in COPILOT_LLM_PROVIDERS. Base URL defaults to http://localhost:11434/v1; the model is never defaulted.
# COPILOT_LLM_OLLAMA_MODEL=llama3.2:3b
# COPILOT_LLM_OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
# Timeout for local providers on the default timeout (1-300; else 30). Keep COPILOT_LLM_BUDGET_S at least this large.
COPILOT_LLM_LOCAL_TIMEOUT_S=30
# ---- CP3 END ----
```
