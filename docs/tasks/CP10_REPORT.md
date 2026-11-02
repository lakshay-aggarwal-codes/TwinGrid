# CP-10 report: frontend mode badge and citations

**Status: built; nothing was executed here.** The sandbox has no `node_modules`, `pytest`, `pydantic` or `fastapi`, and no network. Syntax and types were checked with a bare `tsc` (only unresolved-module noise remained). Every test below must be run on your machine.

## Why this touches the backend (one additive field)
CP-10 asks for "Local model" / "Cloud model (provider name)". `POST /api/copilot/ask` did not say which provider answered (`mode` is only `rule_based` | `llm`), so the badge could not be built honestly. Added `provider: {name, local, fell_back} | null`:
name and data policy only (no URL, model id or key), null for a rule-based answer, optional in the frontend schema so an older backend still parses.

## What changed
- **Backend:** `Answer.provider` (answer.py), set on success in `llm.enhance` from the router's winning provider; `ProviderInfo` and `AskResponse.provider` (schemas.py); route returns it; `docs/api/openapi.json` spliced (round-trip of the committed file checked to be byte-identical before editing). 21 intent goldens gain `"provider": null`; `llm/accepted_rephrase.json` gains `{fell_back: false, local: false, name: "default"}`; `test_copilot_api.py` key sets include `provider`.
- **Badge** (`AnswerView.tsx`, `model.ts`): `Rule-based explanation`, `Model-phrased (evidence-checked) · Local model (ollama)`, `... · Cloud model (groq)`. Rule-based after a failed chain: `Rule-based explanation · model did not answer` / `model wording rejected`. If a later provider answered after an earlier one failed or was skipped, a note says so. `data-source` is `rule | local | cloud | model`; meaning is in words, never colour.
- **Sources** (`AnswerView.tsx`): a "Sources (n)" region, one item per citation with file, heading and a button that moves focus to its evidence row. A source is a link only if the app has a route for exactly that document (`/docs/<path>`); the app has none today, so it is plain text.
- **Slow path, cancel, timeout** (`AssistantDrawer.tsx`): Cancel button while pending; after 4 s a status note (local models are slow); the request is aborted at 30 s (above the server's 12 s chain budget) and shown as a timeout with Retry. A reply that arrives after Cancel or timeout is ignored.
- Warning sentences for `docs_index_unavailable` and `docs_index_stale` (CP-7 codes that were shown raw).
- Synthetic fixtures: `llm_local`, `llm_cloud_fell_back`, `docs_answer`, `docs_not_documented` (passage text is invented, not a quote of any document).

## Tests added
- `tests/test_copilot_provider_info.py` (10): rule-based has none; single, local, failover, cooldown-skip, all-fail, rejected; only `name/local/fell_back` is ever reported; name sanitised; schema accepts and bounds it.
- `model.test.ts` (+7), `AssistantDrawer.test.tsx` (+19): badge per source, fell-back note, screen-reader text, citations (text, link when routed, hostile markup, focus), cancel, late answer ignored, slow note, timeout, no false timeout.
- `e2e/assistant.spec.ts`: `expectDrawerMatches` now checks badge, provider and sources against the real response; new `AI-D-4` asks a docs question in the general drawer and tests keyboard focus from a source.

## Not done / not verified
- **Not run:** `pytest`, `ruff`, `npm run build`, `vitest`, Playwright. If `test_openapi_json_is_not_stale` fails, run `python scripts/gen_api_reference.py` and commit `docs/api/`.
- **No e2e for cancel, slow or timeout:** `e2e/helpers.ts` forbids `page.route`, and the real backend answers too fast to catch. They are unit-tested only.
- **AI-D-4 depends on the docs index** (a build artifact). Without it the test annotates `no-citations` and checks the honest answer; build the index to cover the citation view.
- `docs/copilot/CURRENT_STATE.md`, `docs/CLAIMS.md` and the model card are not updated (CP-11).
- The known CP-6 failure (`what are the Copilot limits-LIMITS.md`) is unchanged.
