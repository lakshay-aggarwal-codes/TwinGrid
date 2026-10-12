# ADR 007: `/api/simulate/{hours}` persists only on request

## Status
Accepted. The code already behaved this way (T14); this records it and pins it.

## Context
UQ-4: should a GET that runs a simulation write rows? Unbounded writes from a read endpoint let any viewer grow the database.

## Options
1. Never persist.
2. Persist only with `persist=true`, operator role, rows stamped `origin='simulated'`, at most 168 rows.

## Decision
Option 2, default `persist=false`. A viewer asking for `persist=true` gets 403 before any computation.

## Consequences
- Read-only by default; stored runs are always labelled simulated and are never mistaken for measurements.
- Retention of persisted runs is not defined here.

## Tests
`tests/api/test_ig05_simulate_persistence.py`; existing `tests/api/test_provenance_writers.py`.
