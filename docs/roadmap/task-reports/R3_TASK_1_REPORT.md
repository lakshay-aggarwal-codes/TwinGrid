# R3 Task 1: What-if range fix

**Verdict: PASSING, ONE RE-RUN PENDING.** Owner's first run (2026-10-25): 104 passed, 1 failed, ruff clean, 117 files formatted.
The failure, `tests/test_scenarios.py::test_schema_bounds_match_what_the_endpoint_enforces`, was the `/api/scenarios` descriptor still
saying 5..15; it is fixed below. Task 1 is Done when `tests/test_scenarios.py` passes. The `ConnectionRefusedError` in the captured
log is the best-effort audit write finding no Postgres; it did not fail any test.

## Cause
The What-if Lab takes its set-point range from the server's actuator range (physics 1: 16..25 C). `GET /api/whatif` and
`GET /api/whatif/sensitivity` capped `chilled_water_temp` at 5..15 C (`SR.CHILLED_WATER_TEMP_BOUNDS`), so the lab got a 422 for
any value above 15 C.

## Change
Same rule Task 3 already uses for the optimizer proposals: accept the union of the registry bounds and the running physics'
actuator range, read per request (`src.optimizer_proposals.accepted_chilled_range_C`).

| Physics | Accepted `chilled_water_temp` |
|---|---|
| legacy-0 | 5..15 C (unchanged) |
| 1 | 5..25 C |
| 2 (no RL actuator range) | 5..15 C (registry bounds) |

- `api/services/scenario_registry.py`: `accepted_chilled_water_range()`, `chilled_water_range_error()`,
  `CHILLED_WATER_TEMP_QUERY_BOUNDS` (outer limit for the query schema, derived from `CHILLED_WATER_ACTION_RANGE_C`, not typed
  twice) and `CHILLED_WATER_TEMP_DESCRIPTION`. `CHILLED_WATER_TEMP_BOUNDS` stays 5..15.
- `api/routes/digital_twin_routes.py`: `/api/whatif` checks the resolved set-point (explicit value or preset) against the running
  physics; outside it is a 422 whose detail names the range.
- `api/plugins/whatif.py`: same check on `/api/whatif/sensitivity`. The sweep's chilled-water limit is now built per request
  (`bounds()`), because a base of 20 C is outside a fixed 5..15 and `plan_sweep` raises for a base outside its bounds.
- `docs/api/openapi.json`: `maximum` 15.0 -> 25.0 and the new description on the two parameters, and the `/api/whatif` docstring.
  Edited by hand, not regenerated (see "Not run").
- `/api/scenarios`: the `chilled_water_temp` descriptor now lists the outer range 5..25 and the same description, so it keeps
  matching the `/api/whatif` schema (`test_schema_bounds_match_what_the_endpoint_enforces` caught this).
- `docs/frontend/contracts/G-SCN.md`: bounds line.
- Tests: `tests/api/test_whatif_chilled_range.py` (new, 22 cases); `tests/api/test_routes_state_whatif.py` 422 case moved from
  20 to 25.1 (20 is valid under physics 1).

## Not changed (on purpose)
- `/api/capacity/headroom`, `/api/economics/summary` and `POST /api/runs` overrides still cap at 5..15. The lab does not call them.
- The preset default set-point stays 7 C (below physics 1's actuator range, inside the accepted range). Task 2 or a later task can
  decide whether it should move.

## Not run
- Every test. `scripts/gen_api_reference.py` (so `openapi.json` and `tests/test_task9_api_reference.py` are unconfirmed).
- Physics 2 fallback beyond the unit test.

## Evidence the owner should paste
```
pytest tests/api/test_whatif_chilled_range.py tests/api/test_routes_state_whatif.py tests/api/test_task15_whatif_sensitivity.py tests/test_scenarios.py tests/test_task15_whatif_sweep.py tests/api/test_task3_recommendation_ranges.py tests/test_task9_api_reference.py -q
ruff check api tests/api
ruff format --check api tests/api
```
If `test_task9_api_reference.py` fails on `openapi.json`, run `python scripts/gen_api_reference.py` and send the diff.
