# G-SCN: Contract Confirmation Record (BC-09 scenario registry)

**STATUS: CAPTURED IN A SANDBOX, NOT YET ON THE REAL BACKEND.**
CAPTURE 1 and 3 are complete. CAPTURE 2 is real output of the BC-09 route and registry code, but produced by an
in-process app (details below), not by your running backend. **Repeat CAPTURE 2 against the real backend
(command below); FE-15 starts only after that diff is clean.**

## Contract (backend)

`GET /api/scenarios` (JWT required, `state` rate-limit bucket) returns
`{ "registry_version": string, "scenarios": ScenarioDescriptor[] }`. There is no `GET /api/scenarios/{id}`.

`ScenarioDescriptor`: `id`, `label`, `kind`, `description`, `weather_source`, `plant`, `control`, `endpoint`, `parameters[]`.
`id` is opaque and stable; a client must never parse it.

`parameters[]` items: `{ name, type: "number" | "enum", unit | null, default, description }` plus
`min`, `max` when `type = "number"` and `options` (string[]) when `type = "enum"`. Order is fixed:
`utilisation, outside_temp, water_stress, mode, chilled_water_temp`. Bounds are generated from the constants
`/api/whatif` enforces (checked by `test_schema_bounds_match_what_the_endpoint_enforces`).

| field | values today | meaning |
|---|---|---|
| `kind` | `workload`, `heat-wave`, `drought` in use; `weather`, `physics-perturbation` allowed, unused | classification only |
| `weather_source` | `constant_input` | ONE outside temperature held for the 24 h run; NOT a reference or recorded series |
| `plant` | `simulated` | the in-repo digital twin, never a real facility |
| `control` | `none` | a scenario is evaluated; nothing is sent to a facility |
| `endpoint` | `/api/whatif` | where to run it |

Unknown values of `kind` / `weather_source` / `plant` / `control` must render as "unknown", never crash.

### Presets (the four scenarios; unlisted parameters use the built-in defaults)

| id | kind | preset |
|---|---|---|
| `whatif-baseline` | workload | defaults |
| `whatif-peak-workload` | workload | utilisation 0.95 |
| `whatif-heat-wave` | heat-wave | outside_temp 38.0 |
| `whatif-drought` | drought | water_stress 0.85 (twin drought threshold is 0.7) |

Defaults: utilisation 0.65, outside_temp 22.0, water_stress 0.0, mode `auto`, chilled_water_temp 7.0.
Bounds: utilisation 0 to 1, outside_temp -10 to 50 (°C), water_stress 0 to 1, chilled_water_temp 5 to 15 (°C).
Modes: `auto`, `free_air`, `closed_loop`, `evaporative`, `hybrid`.

### Running one

`GET /api/whatif?scenario_id=<id>[&utilisation=..&outside_temp=..&water_stress=..&mode=..&chilled_water_temp=..]`
Precedence: explicit query value > scenario preset > built-in default. Unknown `scenario_id` gives 404; out-of-range gives 422.
The response gains `scenario_id` (`null` for a raw what-if).

**Naming trap for FE-15:** descriptor parameters are called `outside_temp` and `chilled_water_temp`, but the
`/api/whatif` response echoes them as `inputs.outside_temp_C` and `inputs.chilled_water_temp_C`. Query names and
descriptor names match; response names do not. Map them explicitly.

## CAPTURE 1: backend content hash
Sandbox copy (BC09 zip as uploaded), sha256:

| file | sha256 |
|---|---|
| `api/services/scenario_registry.py` | `132742b9930286e84ac054be45ed87b54a39255bdff5a7ffb26d9743a51ee82f` |
| `api/routes/digital_twin_routes.py` | `ee173723e5a141cdbd03b62566aa96dad2efac97fdab2170aca7ee9f4f54df4b` |
| `api/routes/scenario_routes.py` | `8f010b71129a5dd802a4ad68398092a1a978964a9cc46a39f66d443b0dc6f0c2` |

On the real checkout, run (PowerShell) and confirm the three hashes are identical, plus record `git rev-parse HEAD`:
```powershell
git rev-parse HEAD
Get-FileHash api\services\scenario_registry.py, api\routes\digital_twin_routes.py, api\routes\scenario_routes.py -Algorithm SHA256
```

## CAPTURE 2: real response
**How it was produced:** the uploaded repo snapshot cannot start the full backend (it is older than your checkout:
`src/versions.py` lacks lineage names; `api/services/live_broadcast_service.py` lacks `broadcast_once` /
`BROADCAST_LOOP_NAME`). So the real `scenario_routes` and `digital_twin_routes` routers and the real registry module
were mounted in a minimal FastAPI app (httpx ASGI transport) with `get_current_user` overridden. The routes, registry,
validation and twin computation are the real code; auth, middleware and the rest of the backend are not exercised.
A sandbox-only stub of `src/versions.py` was needed for the import and is not part of any deliverable.

Files, byte-for-byte from that run:
- `G-SCN.capture-scenarios.json`: full `GET /api/scenarios` body (4 scenarios, `registry_version` "1").
- `G-SCN.capture-whatif-heat-wave.json`: `GET /api/whatif?scenario_id=whatif-heat-wave` body.

Observed status codes: scenarios 200; `scenario_id=nope` 404; `scenario_id=whatif-heat-wave&outside_temp=99` 422;
`scenario_id=whatif-heat-wave&outside_temp=30` 200 with `inputs.outside_temp_C = 30.0` (explicit overrides preset)
and `scenario_id = "whatif-heat-wave"`. Not observed here: 401/403 without a token (relies on the test
`test_scenarios_requires_auth`, which I could not run).

What-if response keys: `hours, basis, inputs, mean_pue, wue, total_water_L, total_energy_kwh, total_co2_kg,
max_outlet_temp_C, final_cooling_mode, drought_override_active, carbon_data_is_real, scenario_id`.
In the sandbox `carbon_data_is_real` is `false` (no carbon CSV present); the numeric values will differ on your backend.

**To capture on the real backend (PowerShell), then diff against the two files:**
```powershell
$t = "<jwt>"
curl.exe -s -H "Authorization: Bearer $t" http://localhost:8000/api/scenarios | Out-File -Encoding utf8 real-scenarios.json
curl.exe -s -H "Authorization: Bearer $t" "http://localhost:8000/api/whatif?scenario_id=whatif-heat-wave" | Out-File -Encoding utf8 real-whatif.json
```
`real-scenarios.json` must equal the committed capture exactly; `real-whatif.json` must have the same keys
(values may differ).

## CAPTURE 3: enum set observed
From the captured `/api/scenarios` body: `kind` = {`workload`, `heat-wave`, `drought`};
`weather_source` = {`constant_input`}; `plant` = {`simulated`}; `control` = {`none`}; `endpoint` = {`/api/whatif`}.
`parameters[].type` = {`number`, `enum`}.

## Verification actually run
- Registry invariants (unique ids, descriptor key set, defaults within bounds, enum default in options, drought preset above
  threshold 0.7, payload is a deep copy): checked in a script, all pass.
- The routes behaviour above, via the minimal app.
- **Not run:** `tests/test_scenarios.py` and `tests/test_api_routes_smoke.py` (they need the full app). Run them on your
  checkout: `pytest tests/test_scenarios.py tests/test_api_routes_smoke.py`.
