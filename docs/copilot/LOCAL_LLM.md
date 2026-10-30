# Local LLM (Ollama) for the Copilot

Nothing leaves your machine when the provider is local. The Copilot still answers from rules if Ollama is off.

## 1. Install and pull a model (Windows PowerShell)

```powershell
winget install Ollama.Ollama
ollama pull llama3.2:3b
ollama list
```

Pick the size for your RAM/GPU (roughly: 3B for 8 GB RAM, 8B for 16 GB or a GPU). Any tag from `ollama list` works.

## 2. Configure (`.env`, backend on the host)

```
COPILOT_LLM_ENABLED=true
COPILOT_LLM_PROVIDERS=ollama
COPILOT_LLM_OLLAMA_MODEL=llama3.2:3b
COPILOT_LLM_BUDGET_S=45
```

`ollama` is a preset: the base URL defaults to `http://localhost:11434/v1` and the provider is flagged local.
The model is never defaulted. `COPILOT_LLM_BUDGET_S` must be at least the local timeout (default 30 s), or the chain budget cuts the attempt short.
Backend in Docker, Ollama on the host: add `COPILOT_LLM_OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`.
Cloud fallback after local: `COPILOT_LLM_PROVIDERS=ollama,groq` (see CP-4 for cloud presets).

## 3. Verify

```powershell
python -m src.copilot.local
```

Prints `ollama: up model=... timeout_s=30`, or `local_down` / `local_model_missing` / `not_configured`. Exit code 0 only if every local provider is up.

## 4. Ollama in Docker (optional, off by default)

```powershell
docker compose -f docker-compose.yml -f docker-compose.ollama.yml --profile ollama up -d ollama
docker compose -f docker-compose.yml -f docker-compose.ollama.yml exec ollama ollama pull llama3.2:3b
```

Then `COPILOT_LLM_OLLAMA_BASE_URL=http://ollama:11434/v1` for a backend on the same compose network.

## Notes

- First question after a cold start can be slow while the model loads; run `ollama run llama3.2:3b "hi"` once to warm it.
- Local timeout: a local provider on the default 10 s timeout gets `COPILOT_LLM_LOCAL_TIMEOUT_S` (default 30). Set `COPILOT_LLM_OLLAMA_TIMEOUT_S` to override.
- llama.cpp server: set `COPILOT_LLM_OLLAMA_BASE_URL` to its `/v1` URL and `COPILOT_LLM_OLLAMA_LOCAL=true`; the health check falls back to `GET /v1/models`.
