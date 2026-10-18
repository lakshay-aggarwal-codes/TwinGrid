# Task 5 (twin parity roadmap): retire `DigitalTwinOptimized` (TG-A-05)

File name note: `docs/tasks/Task5_REPORT.md` already exists in this repo and belongs to an earlier, different
"Task 5" (demo data). It is untouched; this report uses a distinct name.

## Problem
`src/digital_twin_optimized.py` is a second simulator that disagrees with `DigitalTwin`.

## Evidence (sandbox run, 288 benchmark steps, `DigitalTwin(physics_version="legacy-0")` vs `DigitalTwinOptimized`)
| Field | max abs difference |
|---|---|
| `server_inlet_temp_C` | 11 (first step: 14.0 vs 18.0) |
| `server_outlet_temp_C` | 19.98 |
| `cooling_power_kw` / `total_power_kw` | 47.38 |
| `pue` | 0.1047 |
| `water_flow_lpm` | 110.5 |
| `water_consumed_L` | 75,778 |
| `wue` | 30.79 |
| `it_power_kw`, `server_utilisation`, `outside_temp_C`, `humidity_pct`, `water_pressure_bar`, `cooling_mode`, `anomaly` | 0 |

8 of 15 shared fields differ. The optimized state also lacks `water_stress`, `carbon_intensity_gco2_per_kwh`,
`carbon_gco2` and `drought_override_active`. The outlet equation itself is identical; the differences come from
inlet temperature, COP/cooling power and the water model, i.e. a different (older) cooling model, not a rounding issue.

## Decision and trade-off
Retire. Parity would mean re-implementing the main twin's inlet, COP derating, water, carbon and drought logic a second
time and keeping two copies in sync forever. The speed-up is not needed: same protocol, same sandbox, the retired module
took ~3.0 ms/day vs 5.8 ms/day for `DigitalTwin` (legacy-0). Cost of retiring: the benchmark can no longer show a
speed-up (it never had a valid one) and the Numba/batch API is gone.

## Files
- DELETE `src/digital_twin_optimized.py`
- MODIFY `benchmark_performance.py` (no comparison; 3 warm-up days, 30 repeats, fresh twin, median/IQR, environment, optional `--json`; `generate_test_actions` unchanged)
- MODIFY `PERFORMANCE_OPTIMIZATION.md`, `docs/architecture/system.md`, `docs/audit/TwinGrid_Issue_Register.md` (TG-A-05)
- MODIFY `tests/test_audit_regressions.py`: strict xfail removed (module gone); added `test_optimized_twin_is_retired_and_nothing_references_it` and `test_benchmark_actions_are_deterministic_and_drive_both_supported_physics_versions`
- MODIFY `tests/test_time_contract.py`: `ALLOW_LIST` is now empty (its only entry was the retired file; `test_allow_list_has_no_stale_entries` would otherwise fail)
- MODIFY `tests/test_physics_v1_invariants.py`: scope guard no longer skips the retired file and asserts it is gone
- `src/digital_twin.py` untouched.

## Tests run
Owner's machine (Windows 11, Python 3.12.10, pytest 8.4.2), after applying this ZIP:
`tests\test_audit_regressions.py tests\test_time_contract.py tests\test_physics_v1_invariants.py` = 812 passed, 1 skipped
(before the ZIP: 809 passed, 1 failed (stale `ALLOW_LIST` entry), 1 skipped, 1 xfailed).

Benchmark (owner's machine, 30 repeats, numpy 2.5.3): legacy-0 2.518 ms/day (IQR 0.033), physics 1 2.778 ms/day (IQR 0.034).
Sandbox (Linux, 1 vCPU) only: the divergence table above, and 5.83 / 6.56 ms/day.

## Not run
The full test suite; TensorFlow/PyTorch/Postgres-dependent tests; the one skipped test was not investigated.

## Remaining risks
Historical audit documents still mention the old module by name; they describe the state at audit time and were left as is.
