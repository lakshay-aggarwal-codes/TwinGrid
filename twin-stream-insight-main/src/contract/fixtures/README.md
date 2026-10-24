# Contract fixtures

Real captures only, written by `scripts/capture-contract.mjs` from a running backend. Never hand-edit.
The only transformation is credential redaction, listed in each file's `_meta.redactions`.

Each file: `{ "_meta": { endpoint, method, http_status, captured_at, base_url_host, backend_hash, redactions }, "body": ... }`.

**Status: no fixtures captured yet.** Capture with Docker-free `scripts\capture_contract_local.ps1` (repo root, `.venv` active) or against the compose stack with `node scripts/capture-contract.mjs`; then replace this line with the capture date and the backend commit.
