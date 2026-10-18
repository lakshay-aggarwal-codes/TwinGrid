# Task 1 — Physics-aware baseline policies (TG-A-13, part 1)

## Problem and evidence
`src/baselines/policies.py` normalised every set-point with the legacy range 5..15 C. `DataCentreEnv._action_to_control` denormalises with `CHILLED_WATER_ACTION_RANGE_C[physics]`: legacy-0 5..15 C, physics 1 16..25 C. Computed from the code in the audit sandbox: label 5 -> 16.0 C, 7.5 -> 18.25, 10 -> 20.5, 12 -> 22.3, 12.5 -> 22.75, 15 -> 25.0 C actually commanded under physics 1. `test_actuator_limits_match_the_environment` was already failing on the unmodified repo.

## Decisions
- Range is read from the environment's table (`actuator_range_C`), never copied; physics `"2"` raises `UnsupportedPhysicsVersionForRL`.
- Default `physics_version` is `legacy-0` everywhere so every existing call site and the frozen legacy report behave exactly as before (tested against a copy of the old formula for 41 set-points x 4 modes, float32).
- Out-of-range set-points now raise instead of being silently clipped (the clipping is how the mislabelling stayed invisible). Legacy-0 call sites in the repo only use in-range values.
- `RulePolicy` default set-point: legacy-0 12 C (unchanged); physics 1 the middle of the range, 20.5 C. This is a protocol parameter, not tuned; 12 C is below physics 1's reachable range. Task 2 must register it in the physics-1 protocol.
- `PIDPolicy.for_physics` fills limits and nominal set-point from the physics. The controller's memory still starts at the plant's frozen 10 C reset value clipped into the range (as `reset()` always did); under physics 1 the plant starts below its reachable range and its own rate limit walks it up, so the first few PID rate-limit steps are only approximately truthful. Not changed here; flag for Task 2 if tuning is sensitive to it.

## Files
MODIFY `src/baselines/policies.py`, `tests/test_baselines.py` (`test_actuator_limits_match_the_environment` now covers both physics), `docs/audit/TwinGrid_Issue_Register.md` (TG-A-13). CREATE `tests/test_baseline_physics_ranges.py` (14 tests), this report.

## Tests (audit sandbox, Python 3.12, no TF/torch/Postgres; NOT your machine)
- `tests/test_baseline_physics_ranges.py`: 14 passed.
- `tests/test_baselines.py` + `tests/test_policy_evaluation.py` + `tests/test_audit_regressions.py` + new file: 162 passed, 3 xfailed, 5 failed. The 5 failures are the Task-4 set (2 obsolete version-constant tests, 3 tests pinned to the legacy protocol / `baselines-v2`), unchanged by this task; `test_actuator_limits_match_the_environment` now passes.

## NOT done / remaining risk
- This task adds the mechanism only. `src/policy_evaluation.py`, `src/baselines/{tuning,config,evaluation}.py` still construct policies without a physics version, so evaluation and tuning under physics 1 still use the legacy normalisation until Task 2. Do not trust any physics-1 C label before then.
- Recommendation/API ranges: Task 3.
