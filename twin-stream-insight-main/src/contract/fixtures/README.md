# Contract fixtures

Real captures only, written by `scripts/capture-contract.mjs` from a running backend. Never hand-edit.
The only transformation is credential redaction, listed in each file's `_meta.redactions`.

Each file: `{ "_meta": { endpoint, method, http_status, captured_at, base_url_host, backend_hash, redactions }, "body": ... }`.

**Status: no fixtures captured yet.** See `docs/frontend/contracts/README.md`.
