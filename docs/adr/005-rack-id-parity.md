# ADR 005: the backend rack `external_id` is the frontend `rackId`

## Status
Accepted. No mismatch was found, so no code changed.

## Context
UQ-2: the 3D scene renders racks by `rackId`; the backend stores racks as `asset.external_id`. A mismatch would silently show an empty or wrong facility.

## Options
1. Keep one id scheme, generated from one layout, and test equality.
2. Add a mapping table: more state, more drift.

## Decision
Option 1. `scripts/seed_facility.py` `build_layout` writes `zone-<n>-row-<n>-rack-<n>` as `external_id`; `facilityLayout.ts` generates the same string as `rackId`, and `facilityModel` carries `rackId === externalId`.

## Consequences
- Renaming a rack on either side without the other fails a test.
- The test needs Node >= 22.6 and is skipped (not passed) without it.

## Tests
`tests/test_ig05_rack_id_parity.py` (backend ids vs the executed frontend fixture, order and zone included, plus a real seed into SQLite); existing `tests/test_facility_seed.py`; `facilityModel.test.ts` (UQ-2 parity).
