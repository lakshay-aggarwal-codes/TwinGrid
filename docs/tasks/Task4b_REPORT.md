# Task 4b — PID target-inlet search (TG-A-16)

## Problem (measured on the owner's machine, Task 4)
Under physics 1 the tuned PID selected `kp=ki=kd=0` (validation reward -54.8095, identical to the rule baseline) and reward fell monotonically with `kp`/`kd`. The target inlet was a fixed 22 C and was not searched; the reward prefers a warmer inlet (envelope 18..27 C), so any feedback toward 22 C cost reward.

## Change
- `src/baselines/tuning.py`: `TuningSpace.pid_target_inlet_C` is a tuple; default `INLET_TEMP_MAX - (5, 3, 2, 1)` = (22, 24, 25, 26) C (`PID_TARGET_MARGINS_C`, derived from the envelope, not hardcoded); `tune_pid` sweeps targets x gains; candidate key `(target, kp, ki, kd)` so ties pick the smaller (more conservative) target; the config records the SELECTED `target_inlet_C` (the least-violating candidate's when infeasible, information only), per-candidate targets, and the searched list; `TUNER_VERSION = baselines-tuner/3` so existing configs are stale by design.
- Feasibility is unchanged and still absolute: a warmer target that overshoots loses on violations; it never trades a violation for reward.
- `src/baselines/config.py` needed no change (`build_policy` already reads `parameters.target_inlet_C`).
- Tests: grid derived from the envelope and below its upper limit; target selected and recorded, config rebuilds the selected target/gains; ties -> smaller target; infeasible PID still records a numeric target; the three older PID-tuner tests pin `pid_target_inlet_C=(22.0,)` to keep their original meaning.

## Verification
- Sandbox (Linux, Python 3.12, no TF/torch/Postgres): with artifacts generated in a scratch copy (not shipped) `tests/test_baselines.py` + `tests/test_baseline_physics_ranges.py` = **113 passed**. Without artifacts the 3 shipped-artifact tests fail only for missing files, as before.
- Scratch tune (validation scenarios, assumed flat carbon, ONE run): PID -> target 26 C, kp=1, ki=0, kd=0, reward -54.199 (rule -54.809, constant -36.325); 240 candidates, 141 feasible. Rule and constant selections unchanged. This is a sandbox result: the owner's own re-tune is the real one.
- Tune time grows ~4x for the PID block; in the sandbox tune + run took several minutes.

## Required human step
Re-tune and re-run on the owner's machine, then re-run `tests\test_baselines.py` (commands in the chat). Commit `configs/baselines`, `reports/runs/baselines-v3` (regenerated) together with this ZIP's files. `reports/policy_evaluation_physics1/` is NOT affected (the search space is not part of the protocol hash) and must not be regenerated.

## Not done
Held-out test-split numbers were not inspected. Lookup validation reward still not surfaced. The PID still uses the production mode rule.
