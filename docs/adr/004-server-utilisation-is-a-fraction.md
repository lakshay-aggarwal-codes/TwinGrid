# ADR 004: `server_utilisation` is a fraction in [0, 1] at the API boundary

## Status
Accepted. OWNER CONFIRM: the code settles this, but a deployment that feeds percentages in from outside this repo would be affected.

## Context
UQ-1: was `server_utilisation` 0-1 or 0-100? Every producer in this repo uses 0-1: `DigitalTwinState.server_utilisation`, the live loop (`np.clip(..., 0, 1)`), `_diurnal_utilisation` (clamped), `src/sensor_ingestion.py` `RANGES` (0.0, 1.0), and every request parameter (`utilisation` has `ge=0, le=1` on `/api/state`, `/api/benchmark`, `/api/simulate`, `/api/whatif`). The frontend slider is 10-100 and divides by 100 before sending.

## Options
1. Fraction 0-1 everywhere (what the code already does).
2. Percent 0-100 in responses: breaks every request/response symmetry and the sensor range.

## Decision
Option 1. The response field is a fraction of capacity. The frontend schema (`utilisationFraction`) rejects values outside [0, 1]; `units.ts` records `range [0, 1]`, `utilisationToPercent` (null outside [0, 1]) and `percentToUtilisation` (null outside [0, 100]) are the only conversions. The OpenAPI text for `/api/state` and `/api/simulate/{hours}` states it.

## Consequences
- A producer that starts emitting 0-100 fails the schema instead of showing "6500 %".
- A float overshoot such as 1.0000000000000002 would also fail; every current producer clamps, so none occurs.
- The OpenAPI snapshot must be re-captured (descriptions changed): see the IG-05 hand-off.

## Tests
`tests/test_ig05_utilisation_unit.py`; `src/contract/units.test.ts` ("server_utilisation unit boundary").
