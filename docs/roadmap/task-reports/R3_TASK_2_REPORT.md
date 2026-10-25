# R3 Task 2: What-if version info

**Verdict: PASSING, ONE RE-RUN PENDING.** Owner's first run (2026-10-25): 108 passed, 2 failed in the backend list; frontend
`src/contract` 188 passed (10 files, including the 4 new cases); ruff clean (118 files formatted). The two failures were my misses:
- `tests/test_scenarios.py::test_scenario_matches_equivalent_raw_whatif` compared a preset answer with a raw one, and the new
  `provenance` differs in `scenario_kind`. The test now compares provenance explicitly, then everything else.
- `tests/test_task9_api_reference.py::test_openapi_json_is_not_stale`: `openapi.json` still carried the old `/api/whatif` docstring.
  Refreshed from the route's docstring.
Task 2 is Done when those two files pass.

## Change
`GET /api/whatif` now answers with two more keys, additive (every existing key is unchanged):

| Key | Value |
|---|---|
| `physics_version` | The running physics (`active_physics_version()`), reported once at the top level. |
| `provenance` | `origin`, `scenario_kind` (null for a raw what-if), `weather_source` (`constant_input`), `plant`, `control`, `model_version` (null: a what-if applies no learned model), `registry_version` (the preset config), `api_version` (the code that served it). Same vocabulary as a run result's `provenance`. |

- `api/services/scenario_registry.py`: `whatif_provenance(scenario_id, api_version)`, built from the scenario descriptor.
- `api/routes/digital_twin_routes.py`: returns both keys.
- Tests: `tests/api/test_whatif_provenance.py` (new); `tests/api/test_physics_v1_api.py`, `tests/test_runs.py` and `tests/test_scenarios.py` updated for the two
  new keys (a run result carries them beside `outputs`, not inside it).
- Frontend: `src/api/models.ts` and `src/contract/schemas/whatif.ts` accept both as optional (older backends omit them);
  `src/contract/whatifProvenance.test.ts` (new, 4 cases).
- Docs: `docs/frontend/contracts/G-SCN.md` and `G-RUN.md`.

## Not changed
- `docs/api/openapi.json`: only the `/api/whatif` description text changes (the docstring); the response is an untyped object.
- `API_DOCUMENTATION.md`: it does not describe this endpoint's body. Task 14 (docs sync) decides whether it should.
- The git SHA is not in the response: `api_version` is the application version, not a build id.

## Evidence the owner should paste
```
pytest tests/api/test_whatif_provenance.py tests/api/test_physics_v1_api.py tests/test_runs.py tests/test_scenarios.py tests/api/test_routes_state_whatif.py tests/test_task9_api_reference.py -q
ruff check api tests/api
ruff format --check api tests/api
cd twin-stream-insight-main
npx vitest run src/contract
```
