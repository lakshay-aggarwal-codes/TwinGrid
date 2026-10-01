# T0 report — characterization and contract freeze

Task: T0 (roadmap section 7). Production code changed: **none**. Frontend source changed: **none**.

## 1. Changed files (all new)

- `tests/characterization/**` — suite, helpers, tools, this report
- `tests/golden/*.json` — six golden files (`compute_state_grid`, `compute_whatif_grid`, `compute_simulation_cases`, `live_twin_sequence`, `benchmark_pue`, `ws_tick_sequence`)
- `tests/conftest.py`: **not touched** (the optional fixture was avoidable). Markers are registered from `tests/characterization/conftest.py`; the existing HTTP fixtures are re-exported from `tests/api/conftest.py`.
- `pytest.ini`: not touched.

## 2. Determinism finding (constraint 1)

- `src/digital_twin.py` and `src/carbon_provider.py` use **no** `random` / `np.random` (AST-checked in `test_determinism.py`).
- The twin's only wall-clock read is `datetime.now()` as the default `start_time`. Carbon is hour-indexed, so with a real carbon CSV the wall clock would also change numbers; this snapshot has no `data/cleaned/carbon_intensity.csv`, so the flat 475 g/kWh fallback is used (`carbon_data_is_real=False` in every golden row).
- `_tick()` is nondeterministic through `datetime.now()` and `random.uniform` (outside temperature and the water-stress walk).
- Control without editing production code: `datetime` is patched in `src.digital_twin` and `api.services.live_broadcast_service`, `src.carbon_provider.CLEANED_CARBON_PATH` is pointed at a non-existent file, `random` is seeded and restored, and the module singletons (`twin_service._twin`, `_water_stress_state`, `get_session`) are replaced with `unittest.mock.patch.object`.

## 3. What is frozen

- `compute_state(..., live=False)`: 3 utilisation x 4 outside temp x 3 water stress x 5 modes = 180 cases.
- `compute_whatif`: 2 x 2 x 2 x 3 modes at 7 C plus two chilled-water variants = 26 cases.
- `compute_simulation(24, 0.7, 25, 0.3)`: one case (not named in T0 constraint 2; added because `/api/simulate` is otherwise unprotected).
- A fixed 20-step shared-live-twin sequence with accumulators after every step.
- `benchmark_pue` on 14 representative values including both sides of each band edge.
- `_tick()` x 5: key set, value types, values, and the persistence call pattern (one `SensorReading(source="ws")` per tick).
- `ConnectionManager.broadcast` with fake sockets.
- Golden metadata: commit `unknown — no .git in snapshot`, SHA-256 of `src/digital_twin.py`, `api/services/twin_service.py`, `api/services/live_broadcast_service.py`, Python and numpy versions, generation date, scenario id, `physics_version: legacy-0 (implicit)`. Metadata is informational; comparisons use the `data` block with relative tolerance 1e-9.

## 4. Legacy-behaviour and target tests (constraint 6/7)

| Test | Kind | Owner |
|---|---|---|
| `test_api_state_today_persists_one_api_row_and_advances_shared_twin` | legacy | T2 |
| `test_api_state_is_side_effect_free` | strict xfail | T2 |
| `test_api_simulate_get_persists_a_run_and_hourly_rows` | legacy (debt D-1) | T9-T10 |
| `test_healthz_today_echoes_the_raw_exception_text` | legacy | T0b |
| `test_healthz_503_body_contains_no_raw_exception_text` | strict xfail | T0b |
| `test_viewer_scoring_call_today_persists_an_alert` | legacy | T3 |
| `test_viewer_scoring_call_creates_no_alert` | strict xfail | T3 |
| `test_tick_payload_key_set_is_exactly_the_legacy_set`, `test_tick_payload_has_no_origin_or_seq_today` | legacy | T1a |
| `test_ws_payload_contains_origin_and_seq` | strict xfail | T1a |
| `test_broadcast_does_not_complete_while_any_client_is_stalled` | legacy | T4b |

All xfails use `strict=True, raises=AssertionError`. Failure reasons confirmed with `--runxfail`:
`/api/state must not persist rows (assert 1 == 0)`; healthz body contains the injected exception text; `alert ownership ... (assert 1 == 0)`; `{'origin','seq'} <= payload keys` fails.

## 5. Acceptance criteria

1. New non-xfail tests pass on unmodified code — **met**: 37 passed, 4 xfailed.
2. Three consecutive runs identical — **met**: three runs gave `37 passed, 4 xfailed`, and the per-test outcome listings hashed identically.
3. 1% water-constant change fails a golden — **met**, via an in-memory plugin (no file edited):
```
[mutation] src.digital_twin.WATER_FLOW_SCALE_LPM_PER_KW *= 1.01 -> 30.3
FAILED tests/characterization/test_golden_physics.py::test_compute_state_grid_matches_golden
FAILED tests/characterization/test_golden_physics.py::test_compute_whatif_grid_matches_golden
FAILED tests/characterization/test_golden_physics.py::test_compute_simulation_matches_golden
FAILED tests/characterization/test_golden_physics.py::test_live_twin_sequence_and_accumulators_match_golden
FAILED tests/characterization/test_ws_and_manager_contract.py::test_tick_payload_frozen_keys_and_values_match_golden
5 failed, 32 passed, 4 xfailed in 0.57s
```
4. Tree hash of `api/ src/ models/ alembic/ twin-stream-insight-main/src/ notebooks/ scripts/` identical before and after — **met** (`python -m tests.characterization.tools.tree_hash`, excludes `__pycache__`/`*.pyc`): `9ea413b7d74512422f80e432d3ed867358686d661a1b2f519520da19691b88cc`
5. xfail tests fail for the stated reason, not fixture errors — **met** (section 4).

## 6. Test-count discrepancy (constraint 8) — PARTLY RESOLVED

`python -m tests.characterization.tools.inventory` on this snapshot:
```
file                                                    def test_ collected
tests/api/test_routes_alerts_webhooks.py                       23        35
tests/api/test_routes_auth_refresh.py                          18        20
tests/api/test_routes_health_metrics.py                        10        14
tests/api/test_routes_optimize_esg_shadow.py                   19        25
tests/api/test_routes_state_whatif.py                          17        26
tests/api/test_websocket.py                                     6         6
tests/simple_tests.py                                           3         0
tests/test_anomaly_alerts.py                                    6         6
tests/test_anomaly_detector.py                                 29        32
tests/test_api_routes_smoke.py                                 28        37
tests/test_auth_security.py                                    13        13
tests/test_carbon_is_real_flag.py                               3         3
tests/test_data_generator_consistency.py                        4         4
tests/test_data_pipeline.py                                    24        24
tests/test_db_url.py                                           11        16
tests/test_digital_twin.py                                     29        29
tests/test_digital_twin_dynamic.py                             13        13
tests/test_drought_override.py                                  8         8
tests/test_ingestion.py                                        17        17
tests/test_live_broadcast.py                                    7         7
tests/test_optimization_service.py                              8         8
tests/test_optimizer_observation_space.py                       3         3
tests/test_predictive_maintenance.py                            5         5
tests/test_security_hardening.py                               18        18
tests/test_serialization.py                                     8         8
TOTAL                                                         330       377
files with test defs that pytest never collects: ['tests/simple_tests.py']
```
- 330 `def test_` -> 377 collected: parametrisation adds 47 items, and `tests/simple_tests.py` (3 defs) is never collected because `python_files = test_*.py`.
- In my sandbox the existing suite gives 363 passed, 6 failed, 8 errors; all 14 are in `tests/test_anomaly_detector.py` and caused by TensorFlow not being installed in the sandbox (`ImportError: TensorFlow required`). With the new suite: 400 passed, 4 xfailed, same 14 TensorFlow failures.
- **The owner's "214 passed" is not reproducible from this snapshot** (NOT VERIFIED). Likely causes are a different commit, a deselected subset, or a different command. Please run `python -m pytest --collect-only -q | Select-Object -Last 3` and `python -m pytest -q` locally and compare with the table above.

## 7. Commands (PowerShell)

```
python -m pytest tests/characterization -q
python -m pytest tests/characterization -q --runxfail
$env:TWINGRID_MUTATE = "src.digital_twin:WATER_FLOW_SCALE_LPM_PER_KW:1.01"; python -m pytest -p tests.characterization.tools.mutation_plugin tests/characterization -q -o addopts=""; Remove-Item Env:TWINGRID_MUTATE
python -m tests.characterization.tools.tree_hash
python -m tests.characterization.tools.inventory
python -m tests.characterization.golden_support --regenerate   # only on reviewed, unmodified code
```

## 8. Deviations, risks, not run

- Frontend suite not run (no frontend change; `node_modules` not present in the snapshot). Full backend suite run on Python 3.12.3 / numpy 2.4.4 / pandas 3.0.2 without TensorFlow and without PostgreSQL (SQLite in-memory, as the existing fixtures do).
- Goldens were generated with numpy 2.4.4. If your numpy differs, a 1e-9 relative mismatch is possible; if so, report it before regenerating.
- `conftest.py` imports fixtures from `tests/api/conftest.py`; if a later task renames those fixtures, update that import.
- Goldens freeze known-wrong physics (for example the water and carbon issues from the forensic review) by design; they are not endorsements. T7 re-baselines them.

## 9. Rollback

Delete `tests/characterization/` and `tests/golden/`. No data, schema or config involved.
