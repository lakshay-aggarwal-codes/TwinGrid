# Copilot: current state (CP-0 baseline)

Describes the Copilot as it is in the supplied repo before the CP roadmap changes anything. Frozen by
`tests/characterization/copilot/`. Later tasks update this file when they change a row.

## Request path

`POST /api/copilot/ask` (`api/plugins/copilot.py`) -> `answer.answer_question` (`src/copilot/answer.py`):

1. `classify(question, kind)`: first keyword match wins, in this order: `what_changed`, `model_limits`, `why_red`,
   `current_status`, `what_is_this`; no match falls back to the context kind (`alert` -> `why_red`, `model` ->
   `model_limits`, `signal` -> `current_status`, `feature` -> `what_is_this`, else `fallback`). `what_is_this` on an
   alert becomes `why_red`. Matching is by substring on the lower-cased question (so "preferred" matches "red").
2. One builder per intent fills a template from evidence collected by read-only tools (`src/copilot/tools.py`).
   Numbers and names appear only as `[E#]` markers. History is accepted but never used.
3. Answer is clipped to 1500 characters; if a number in the text is not backed by evidence, the answer is replaced by a
   fixed sentence and the warning `answer_numbers_unbacked` is added.
4. `llm.enhance` (`src/copilot/llm.py`) optionally rephrases it. It never raises.

Intents: `why_red`, `what_is_this`, `model_limits`, `current_status`, `what_changed`, `fallback`.
`why_red` raises `tools.NotFound` for an unknown alert (the route answers 404).

## Environment variables

| Variable | Default | Read where | Meaning |
| --- | --- | --- | --- |
| `COPILOT_LLM_ENABLED` | `false` | `llm.load_settings` | `1/true/yes/on` (any case) turns the optional rephrase on |
| `COPILOT_LLM_BASE_URL` | empty | `llm.load_settings` | OpenAI-compatible base including `/v1`; trailing `/` stripped; `POST <base>/chat/completions` |
| `COPILOT_LLM_MODEL` | empty | `llm.load_settings` | model id sent to the provider; the only model name logged |
| `COPILOT_LLM_API_KEY` | none | `api.secrets.read_secret` via `llm.load_settings` | Bearer key |
| `COPILOT_LLM_API_KEY_FILE` | none | `api.secrets.read_secret` | file holding the key; wins over `COPILOT_LLM_API_KEY` |
| `COPILOT_LLM_TIMEOUT_S` | `10` | `llm.load_settings` | 0.1 to 120; a bad value falls back to 10 |
| `COPILOT_LLM_MAX_OUTPUT_TOKENS` | `400` | `llm.load_settings` | 16 to 4000; a bad value falls back to 400 |
| `COPILOT_LLM_LIVE_TEST` | unset | `tests/copilot_conftest_plugin.py` | `1` selects the `live_llm` test; otherwise it is deselected |
| `RATE_LIMIT_STATE` | `30/minute` | `api/config.py` (`rate_limit_setting("state")`) | the `ask` route uses the existing `state` limit class |

Settings are read on every call (no caching). With `COPILOT_LLM_ENABLED` false, nothing else is read and no outbound call
is made. Documented in `.env.example` (block T24) and `docs/env/T24.md`.

## Optional LLM rephrase: outcomes

| Outcome | Condition | Result | Log `outcome=` |
| --- | --- | --- | --- |
| off | not enabled | unchanged rule-based answer, no warning, `limits.provider_configured=false` | (no line) |
| not configured | enabled, no base URL or no model | rule-based + `llm_unavailable`, `provider_configured=false` | `not_configured` |
| nothing to phrase | no evidence, or `answer_numbers_unbacked` | rule-based, no warning, `provider_configured` as configured | (no line) |
| accepted | reply passes `llm.validate` | `mode=llm`, text replaced, evidence unchanged | `ok` |
| rejected | reply fails `llm.validate` | rule-based + `llm_rejected` | `rejected_<code>` |
| unavailable | provider trouble | rule-based + `llm_unavailable` | `unavailable_<code>` |

Rejection codes: `bad_shape`, `unknown_evidence`, `empty`, `control_chars`, `unknown_placeholder`,
`malformed_placeholder`, `too_long`, `html`, `url`, `unbacked_number`, `dropped_cause_unknown`, `forbidden_wording`
(checked in that order). Unavailable codes: `timeout`, `network`, `http_429`, `http_5xx`, `http_3xx`, `http_4xx`,
`too_large` (over 256 KiB), `bad_envelope`, `invalid_json`. A redirect is never followed.

Request sent to the provider: `model`, `messages` (system policy + one user message holding a delimited data block),
`max_tokens`, `temperature=0`, `stream=false`; no tools. The data block holds `question`, `evidence`, `unknowns`,
`allowed_links` and `draft`. Numeric evidence values are withheld (`value: null`); string and boolean values are sent.

## Known gaps against the CP contract (recorded, not fixed in CP-0)

- **Privacy (contract rule 7, CP-8):** the question text and string-valued evidence are sent to the provider. That
  includes the stored alert message (evidence field `message`, also quoted inside `draft`) and the alert id (evidence
  `entity`, e.g. `alert:42`). Recorded in `golden/llm/accepted_rephrase.json`. CP-8 must remove these and re-record.
- **Single provider only (CP-1, CP-2):** no chain, cooldown or time budget; one provider failure goes straight to
  rule-based.
- **No local-only mode (CP-8)** and no per-intent data policy.
- **No docs retrieval (CP-5 to CP-7);** `what_is_this` reads only `docs/copilot/capabilities.json`.
- **Routing is by substring** (see step 1), so some questions route oddly. Pinned in `test_routing_table`, not a goal.

## Tests that cover this today

- Existing: `tests/test_copilot_answer.py`, `test_copilot_llm.py`, `test_copilot_tools.py`, `test_copilot_catalogue.py`,
  `test_copilot_adversarial.py`, `test_copilot_api.py`; frontend contract fixtures in
  `twin-stream-insight-main/src/contract/fixtures-copilot/`.
- CP-0: `tests/characterization/copilot/` (goldens in `golden/`; re-record only on purpose with `COPILOT_CHAR_UPDATE=1`).
