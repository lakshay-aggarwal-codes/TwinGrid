# Contract fixtures

Real captures only, written by `scripts/capture-contract.mjs` from a running backend. Never hand-edit.
The only transformation is credential redaction, listed in each file's `_meta.redactions`.

Each file: `{ "_meta": { endpoint, method, http_status, captured_at, base_url_host, backend_hash, redactions }, "body": ... }`.

**Status: captured 2026-10-24** with `scripts\capture_contract_local.ps1` (throw-away database, simulated data), backend commit
`8b96cb1cd82e22ff04639ade221c486968ff4149`. 11 JSON files (8 REST responses, 3 live WebSocket frames) plus `openapi/typed.json` (8 typed models).
`npx vitest run src/contract`: 9 files, 184 tests passed, 0 skipped (owner's run, 2026-10-24).

Known gaps in this capture (not errors; re-capture when the cause is gone):
- `alerts.json` is an empty list, so the alert record shape is not exercised. Re-capture once an alert exists.
- `POST /api/optimize` returned 503, so there is no `optimize` fixture.
- `GET /api/facility` and `GET /api/assets` returned 404, so there are no `facility`, `assets` or `edges` fixtures.
