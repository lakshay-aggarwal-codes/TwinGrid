# Task 2 — Physics-aware tuning, config lineage and protocol (TG-A-13 part 2, TG-A-15)

## What changed
- `src/policy_evaluation.py`: `constant_grid_c(physics)` (5 evenly spaced points incl. both ends of the env's range: legacy-0 `5, 7.5, 10, 12.5, 15` exactly as the frozen protocol; physics 1 `16, 18.25, 20.5, 22.75, 25`). `EvalConfig` defaults are physics 1's (grid above, rule 20.5 C = `default_rule_setpoint_C("1")`) and `__post_init__` refuses set-points outside the declared physics' range ("registered per physics"). `constant_grid` and `run_evaluation` build policies with `physics_version`.
- `src/baselines/tuning.py`: all four tuners use the physics' range; PID via `PIDPolicy.for_physics`; PID limits recorded from the range; `pid_nominal_setpoint_C` and `rule_chilled_C` from the physics; `lookup_transient_steps_excluded` derived (`ceil(max(|10-lo|, |hi-10|) / 2 C per step)`: legacy-0 3 as before, physics 1 **8**); `TUNER_VERSION = baselines-tuner/2`; each config's `tuning.actuator_range_C` recorded.
- `src/baselines/config.py`: `check_lineage` treats a config whose recorded actuator range differs from the physics' (or is absent, i.e. tuned by /1) as `BaselineConfigStale("tuning.actuator_range_C")`; `build_policy` builds in the config's physics (`lineage.physics_version`).
- `scripts/eval_policies.py`: rule/best-constant built with the config's physics.
- `configs/prereg/prereg_v2.json` + `.lock.json`: **re-registered** (TG-A-15, amendment A3; see the register). Old sha `1fe941db…` -> new `2973cd13…`.

## Decisions / trade-offs
- Default `EvalConfig` is physics 1. The frozen legacy-0 protocol loads unchanged (explicit values in its JSON): test pins its `preregistration_sha256` and its grid/rule.
- Validation at construction is deliberately strict: a legacy grid on physics 1 can no longer exist silently. Cost: two protocol files had to be handled (the committed policy-evaluation protocol is legacy-0 and valid; `prereg_v2.json` was not).
- The repo's two strict xfails (T20: "harness still encodes constants on the legacy 5-15 C axis") are now real passing tests; the two obsolete version-bump tests in `test_baselines.py` were fixed here instead of Task 4 (they bump to a value derived from the current one).
- PID memory start under physics 1 (plant resets at 10 C, below the reachable range): unchanged (clipped into range). A tiny physics-1 smoke tuning in the sandbox gave all four baselines feasible; that is NOT a result, only a sanity check (2 validation scenarios per family).

## Tests (audit sandbox, Python 3.12; no TF/torch/Postgres; not your machine)
- New/changed: `tests/test_baseline_physics_ranges.py` 21 passed; `test_policy_evaluation.py`, `test_audit_regressions.py` pass; `test_robustness_eval.py` 101 passed after re-registration.
- Whole suite vs the unmodified repo: failure sets compared (union over 6 chunks). **No new failures.** Fixed vs original: `test_actuator_limits_match_the_environment` and the two version-bump tests. Remaining `test_baselines.py` failures: the 3 "shipped" tests (`test_shipped_configs_are_valid_current…`, `test_shipped_baselines_run_verifies…`, `test_shipped_baselines_run_reproduces_on_rerun`) -> Task 4 (need your regenerated protocol/configs/run). Other failures are unchanged environment ones (TensorFlow/torch/Postgres missing in the sandbox, one `.gitignore` test).

## NOT done
- No physics-1 protocol, `configs/baselines/*`, or `reports/runs/baselines-*` generated here (Task 4, on your machine). Your current `configs/baselines/*` (tuner /1) are now stale by design.
- `baselines` CLI default `--prereg` still points at the legacy-0 protocol; it therefore refuses to run without `--prereg` (the guard message says so).
- Recommendation/API ranges: Task 3.
