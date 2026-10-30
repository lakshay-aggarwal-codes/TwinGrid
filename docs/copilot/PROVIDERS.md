# Free-tier provider presets (CP-4)

Last verified: **2026-10-31** (read from provider pages and third-party summaries, no live calls). Free tiers change without
notice: re-check the provider's own page before relying on a number. Lists worth re-checking periodically: the cheahjs
and mnfst free-LLM-API lists and the free-llm-api-hub dataset.

One provider = one account = one key. Never add several accounts of one provider to get more quota (limits are
account-wide, and that breaks contract rule 5). Failover is across different providers (CP-2).

## Setup (`.env`; names only here, keys never in the repo)

```
COPILOT_LLM_ENABLED=true
COPILOT_LLM_PROVIDERS=ollama,groq,openrouter
COPILOT_LLM_GROQ_MODEL=<model id from the provider's list>
COPILOT_LLM_GROQ_API_KEY=            # or COPILOT_LLM_GROQ_API_KEY_FILE
# optional: COPILOT_LLM_GROQ_RPM=24  COPILOT_LLM_GROQ_RPD=900   (0 = no client-side limit)
```

The base URL is filled in from the preset when `COPILOT_LLM_<NAME>_BASE_URL` is empty. Models are never defaulted.

## Presets

| Name | Base URL (we append `/chat/completions`) | Auth | Model id shape | Default client limit (rpm / rpd) | Provider docs |
|---|---|---|---|---|---|
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | Bearer | `gemini-...` | 5 / 100 (placeholder, NOT verified) | https://ai.google.dev/gemini-api/docs/openai |
| `groq` | `https://api.groq.com/openai/v1` (`/openai` is required) | Bearer | `llama-3.3-70b-versatile`, `openai/gpt-oss-...` | 24 / 900 (published 30 rpm; daily caps differ per model) | https://console.groq.com/docs/rate-limits |
| `openrouter` | `https://openrouter.ai/api/v1` | Bearer | `vendor/model:free` | 16 / 50 (published 20 rpm; 50/day, 1,000/day after buying $10 of credits: set `_RPD=1000`) | https://openrouter.ai/docs/api-reference/limits |
| `github` | `https://models.github.ai/inference` | Bearer (token with `models: read`) | `publisher/model`, e.g. `openai/gpt-4.1` | 5 / 50 (placeholder, NOT verified) | https://docs.github.com/en/rest/models/inference |

Defaults are deliberately below the published limits. Provider limits are per account/organisation, not per key or per model
(Groq, OpenRouter), so our counters are per provider name.

## Quirks (from provider docs; not hit live)

- **Groq:** the `/openai` segment in the URL is required. `temperature: 0` (what we send) is converted by Groq to a tiny value; harmless.
- **OpenRouter:** free-model quota is shared by all `:free` ids; a negative balance returns 402 even on free models. We treat 402 as a transient failure (back off, retry later), not auth.
- **GitHub Models:** a token without `models: read` gives 403. The router treats 403 as auth and disables that provider until restart.
- **Gemini:** OpenAI-compatible layer only; limits vary by model and change often.
- No provider needs extra headers for our request shape; none are sent.

## Data-use terms: verify before use

I did not verify any provider's data-use terms. Free tiers often allow providers to use prompts to improve products. Our requests
carry the question, evidence items with numbers withheld, and (from CP-7) doc passages, never raw telemetry or user identifiers.
Read each provider's terms yourself; keep sensitive deployments on the local provider (CP-3).

| Provider | Terms page to read | Status |
|---|---|---|
| Gemini | https://ai.google.dev/gemini-api/terms | unverified |
| Groq | https://console.groq.com/docs/legal | unverified |
| OpenRouter | https://openrouter.ai/docs/guides/privacy | unverified |
| GitHub Models | https://docs.github.com/en/github-models | unverified |

## Client-side limiter

Sliding windows (60 s, 24 h) per provider, in this process only; multi-worker deployments each count separately. When a window
is full the provider is skipped with outcome `unavailable_client_rate_limit` and the router puts it in cooldown until the window
frees. A provider's own 429 still fails over as in CP-2.
