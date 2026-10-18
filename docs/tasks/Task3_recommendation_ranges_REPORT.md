# Task 3 (TwinGrid roadmap) — Recommendation and proposal ranges

> File name note: `docs/tasks/Task3_REPORT.md` already exists in the repo and belongs to a different task list
> ("Frontend dependency security"). It is NOT touched; this report has its own name.

## Verdict
A genuine scale mismatch existed. For the shipped baseline configs under physics 1, the API reported **12.0 C** for an
action the evaluation executed at **22.3 C**, and could not accept the evaluated range at all (accepted 5..15 C; physics 1
executes 16..25 C — the two ranges do not overlap). Fixed, with tests that fail on the unmodified zip.

## Data flow (traced from code)
1. `GET /api/optimizer/baseline-recommendation` -> `api/plugins/optimizer_proposals.py::compute_recommendation` ->
   `_recommend` -> `src/baseline_recommendation.py::recommend`.
2. `recommend` loads `configs/baselines/{pid,rule}.json`, `check_lineage` (physics, env, reward versions must equal the
   running code; `src/versions.py::running_compat_values` uses `active_physics_version()`), ranks by stored validation reward.
3. `_setpoint` -> `src/baselines/config.py::build_policy(cfg)` -> policy `.act()` returns a **normalised** action in [0,1].
   `build_policy` passes no `physics_version`, so policies normalise on the **legacy 5..15 C** range (12.0 C -> 0.7).
4. Evaluation/tuning run those same actions through `src/rl/env.py::DataCentreEnv._action_to_control`, which de-normalises
   with `CHILLED_WATER_ACTION_RANGE_C[physics]`: legacy-0 5..15, physics 1 16..25 -> 0.7 executes as **22.3 C**.
5. OLD `_denormalise` used 5..15 under every physics -> reported 12.0 C. Then `_predict` ->
   `twin_service.compute_whatif` -> `DigitalTwin(initial_chilled_water_temp_C=<C>)`: the twin consumes real degrees C
   (accepts 0..40) and runs `active_physics_version()` = physics **1** by default (`src/versions.py::PHYSICS_VERSION`).
   So the prediction was simulated at 12 C while the stored validation reward was earned at 22.3 C.
6. Inputs: `ProposalCreate` / `SandboxQuery` bounded to `rules.CHILLED_MIN_C/MAX_C` = 5..15 (legacy), registry
   `SR.CHILLED_WATER_TEMP_BOUNDS` = 5..15, `SR.WHATIF_DEFAULTS["chilled_water_temp"]` = 7.0. A physics-1 recommendation
   (16..25) therefore could not even be proposed unchanged.

Shipped configs (evidence): `rule.json` chilled_C 12.0; `pid.json` gains kp=ki=kd=0 (so PID == rule, identical stored
reward -54.1855), nominal 12.0, limits 5..15, lineage physics `"1"`. These are the provisional pre-TG-A-13 configs.

## Decision and trade-off
* **Report the degrees C the evaluation executed.** `baseline_recommendation._denormalise(action, physics)` uses
  `policies.actuator_range_C(config lineage physics)`. This is correct whether `build_policy` still builds legacy-scale
  policies (today) or physics-aware ones (after roadmap Task 2): the action is what was executed either way.
* PID "current set-point" input: converted from real C to the policy's own scale via the normalised position
  (`_to_policy_scale`, uses `policy.physics_version` added by Task 1); clipped to the actuator range if outside, and the
  `basis` text says so. When the policy scale differs from the config physics, `basis` says the values were converted.
* A config whose set-points the policy rejects (`ValueError`) is now skipped with a reason, not a 500.
* **Input bounds = union** of registry bounds and the running physics' actuator range (`accepted_chilled_range_C`), read per
  request. Chosen over "exactly the actuator range" because the frontend slider takes its bounds from the registry
  (5..15) and I may not edit either; a strict range would make every slider value a 422. Trade-off: under physics 1
  values 5..15.99 are still accepted, so they are **flagged, not blocked**.
* **Additive payload** (backward compatible): `selected.physics_version`, `selected.actuator_range_C`, and
  `predicted.setpoint_check = {physics_version, actuator_range_C, proposed_within_actuator_range,
  reference_within_actuator_range}`.
* legacy-0 deployments (`PHYSICS_VERSION=legacy-0`): identical bounds and identical numbers (tested).

## Files
MODIFY `src/baseline_recommendation.py`, `src/optimizer_proposals.py`, `api/plugins/optimizer_proposals.py`,
`tests/test_task19_optimizer_rules.py` (one assertion), `tests/api/test_task19_optimizer_proposals.py` (two assertions).
CREATE `tests/test_recommendation_ranges.py` (12), `tests/api/test_task3_recommendation_ranges.py` (9), this report.

Two existing assertions encoded the bug and were changed: rule set-point `== 12.0` -> `lo + 0.7*(hi-lo)` of the running
physics; API `5 <= x <= 15` -> the running physics' range; and the "just above max" case `15.1` -> `25.1` (15.1 is
now a valid physics-1 input, still flagged).

## Tests run (this sandbox: Linux, Python 3.12.3, deps from requirements.txt; NOT your Windows machine)
* New tests on the unmodified zip: 12/12 and 5/9 fail (the other 4 are rejection cases that hold both before and after);
  after the fix 21/21 pass.
* Regression set `tests/api`, `test_task19_optimizer_rules`, `test_baselines`, `test_baseline_physics_ranges`,
  `test_policy_evaluation`, `test_audit_regressions`: **before 34 failed / 817 passed; after 34 failed / 826 passed**;
  the sorted failure lists are identical (no new failure, no fixed one). The +9 are the new API tests.
* The 34 are pre-existing, unrelated to this task, and I did not root-cause all of them: 14 `test_error_contract`,
  5 `test_provenance_writers`, 5 `test_baselines`, 3 `test_task19_optimizer_rules`, 6 single failures in other API files.
  The 3 in `test_task19_optimizer_rules` are tied to the provisional configs (they expect PID reward -91.05 / kp=1 / rule
  -92.16; shipped configs have PID gains 0 and equal rewards) — Task 4 regenerates the configs and must repair them.
  I did not edit configs or loosen those tests.

## NOT run / not verified
* Your machine; the frontend; `tests/test_recommendation_ranges.py` full suite beyond the files above; Postgres.
* Ruff/pyrefly not run (ruff unavailable in the sandbox).
* Task 4's regenerated configs do not exist yet; the identity path for physics-aware policies is tested with a stub
  (`monkeypatch` of `build_policy`), not with real Task-2 configs.

## Remaining risks / dependencies
1. **Roadmap Task 2 must make `build_policy` physics-aware** (and store `lineage.actuator_range_C`). Until then physics-1
   set-points like 22.75 C cannot be built (legacy range) and such a config is skipped with a "re-tune" reason.
2. `scenario_registry.CHILLED_WATER_TEMP_BOUNDS` (5..15) and `WHATIF_DEFAULTS` (7.0 C) are legacy-scale; they also feed
   `/api/whatif`, `api/schemas/runs.py`, `api/plugins/capacity.py`. Out of scope here. Under physics 1 the default
   reference run (7 C) is outside the evaluated range (`reference_within_actuator_range: false`).
3. The proposal safety check only tests the outlet limit; a 5..15 C proposal under physics 1 is flagged but still
   recordable although the evaluation treats the resulting inlet as a hard-constraint violation. Decide whether to refuse.
4. `DigitalTwin` is not the same plant as `DigitalTwinOptimized` (audit); predictions remain simulated, carbon flat 475 g/kWh.

## Frontend contract impact (frontend not edited)
Additive only: new keys above. Visible consequences: recommended chilled-water values now read 16..25 C under physics 1
(previously 5..15); sandbox/proposal inputs up to 25 C are accepted; slider bounds from the registry still end at 15 C, so
the UI cannot yet *enter* the recommended value by slider. `docs/frontend/contracts/` captures were not touched.
