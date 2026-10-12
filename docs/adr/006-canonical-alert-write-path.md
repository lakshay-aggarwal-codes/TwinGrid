# ADR 006: one function writes alert rows

## Status
Accepted.

## Context
UQ-3: two code paths built `Alert` rows. `data_repository.save_alert` (used by the anomaly pipeline) keeps `dedupe_key`, `origin` and `model_version`; `AlertManager.raise_alert` in `src/alert_system.py` built the row itself and dropped all three. `raise_alert` has no caller in this repo, so it was a latent second path. One more caller, the deprecated `/api/anomaly/score` rollback path, already goes through `save_alert` but passes no provenance (development-only, `ANOMALY_SERVER_SIDE=false`).

## Options
1. Route every writer through `save_alert` and gate the rest with a test.
2. Delete `raise_alert`: loses the email/Slack delivery it also performs.

## Decision
Option 1. `raise_alert` now calls `save_alert`, takes `origin` as a required keyword (an alert without provenance is not written) and forwards `dedupe_key` and `model_version`. A test scans `api/`, `src/` and `scripts/` with the AST and fails on `Alert(...)`, `insert(Alert)` or raw `INSERT INTO alerts` outside `api/repositories/data_repository.py`.

## Consequences
- A new caller of `raise_alert` must state `origin`.
- The legacy rollback route still writes rows with NULL provenance. OWNER CONFIRM: remove that route path, or give it an explicit origin.

## Tests
`tests/test_ig05_alert_write_path.py`; existing `tests/characterization/test_t3_routes_repo_migration.py`.
