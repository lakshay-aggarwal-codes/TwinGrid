# Copilot fixtures (SYNTHETIC)

Hand-written from playbook section 8.4, NOT captured from a running backend. They exist so the assistant UI can be
built and tested before the backend (Task 14) is deployed. Replace with real captures once the endpoint exists
(`scripts/capture-contract.mjs`); a mismatch then is a contract finding, not a reason to loosen the schema.

- `rule_based`, `stale`, `unknown_cause`, `refusal`, `llm_fallback`: 200 responses.
- `hostile_text`: markup and bad links inside server text; the UI must show them as text and drop the links.
- `rate_limited`: the 429 shape (status, `Retry-After`). `offline`: the network is down; no response exists.
