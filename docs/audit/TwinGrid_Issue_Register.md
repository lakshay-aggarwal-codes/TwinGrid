# TwinGrid Issue Register (deep audit, 2026-10-18)

Status key: **FIXED** = code changed and a regression test passes in the audit sandbox; **CONFIRMED-OPEN** = verified, not fixed; **RISK** = plausible, not verified; **FEATURE** = suggestion.
Severity: Critical / High / Medium / Low as defined in the audit brief. "Confidence" is confidence the defect is real.

## Confirmed defects

### TG-A-01 — Evaluation reports one physics, runs another  (Critical, FIXED, confidence high)
- Files: `src/policy_evaluation.py` (`run_episode`, `EvalConfig.physics_version`, `PHYSICS_VERSION`).
- Evidence: `run_episode` built `DataCentreEnv` without `physics_version`, so the env used the process default (`1`) while the report said `legacy-0 (implicit)`. The checked-in report reproduces exactly under legacy-0 (rule, `stress_0.0/test/200000`: reward -196.3821, 288 under-min steps); the same config through the old code path ran v1 (reward -63.657, 0 under-min steps).
- Root cause: optional argument never passed; a free-text label instead of a canonical version.
- Fix: label resolved by `resolve_physics_version`, passed explicitly, mismatch raises `PhysicsMismatchError`, results carry `physics_version_executed`. Legacy label still maps to legacy-0 so the committed protocol reproduces.
- Tests: `tests/test_audit_regressions.py` (6 tests incl. reproduction of the committed report).
- Effort: done. Blockers: none.

### TG-A-02 — Inlet under-minimum tolerated by a baseline-relative gate  (Critical, FIXED, high)
- Files: `src/policy_evaluation.py` (`decide_outcome`, `OUTCOME_RULES`, `run_evaluation`).
- Evidence: gate required `inlet_under_min_steps <= rule baseline`; baseline-safety check ignored under-min; a unit test encoded this.
- Fix (amendment A1): all three counted limits (`HARD_CONSTRAINT_METRICS`) must be zero, absolutely, for the candidate and for any baseline offered as a replacement. "Best constant" now chosen among envelope-feasible constants (flag `best_constant_envelope_feasible`).
- Note: no PPO candidate has been scored under the old rule, so the amendment cannot have been fitted to a result. It is still a change to a preregistered rule and must be disclosed.
- Tests: 3 new decision tests, 2 harness tests.

### TG-A-03 — Physics v2 accepted, then `KeyError` in RL reset  (High, FIXED, high)
- Files: `src/rl/env.py`, `src/optimizer.py`. Now `UnsupportedPhysicsVersionForRL` at construction. Full v2 RL support (action range, obs schema, baselines, policies) is NOT implemented; see roadmap.

### TG-A-04 — Baseline lineage records the running physics, tuning could use another  (High, FIXED, medium-high)
- Files: `src/baselines/{config,evaluation,cli}.py`. Guard `assert_eval_physics_matches_lineage`; `--prereg` option added.

### TG-A-05 — "Optimized" twin is not numerically equivalent  (High, CONFIRMED-OPEN, high)
- Files: `src/digital_twin_optimized.py`, `benchmark_performance.py`, `PERFORMANCE_OPTIMIZATION.md`.
- Evidence: on the benchmark inputs max |d outlet| ~ 20 C, max |d PUE| ~ 0.10 vs `DigitalTwin(legacy-0)`. Used only by the benchmark and two tests.
- Done: strict xfail documenting it; benchmark success banner removed; perf doc rewritten. Not done: fix or retire the module.

### TG-A-06 — Performance claims false and unreproducible  (High, FIXED in docs, high)
- Doc claimed 45 s / 3.844 s -> 0.003 s and cited non-existent modules. Measured: main twin ~3.3 ms per simulated day. Single run, one machine; rewritten as indicative only.

### TG-A-07 — Shipped baseline configs stale vs environment v2  (High, CONFIRMED-OPEN, high)
- 6 failing tests in `tests/test_baselines.py` on the unmodified repo: `lineage.environment_version` recorded `1`, code is `2`; `requirements.lock` hash differs.
- Fix requires re-tuning under a physics-1 protocol on the owner's machine (commands in the verification summary). Not done here: artifacts generated in the audit sandbox would carry the sandbox's hashes.

### TG-A-08 — CI type gate deliberately red  (Medium, CONFIRMED-OPEN, high)
- `.github/workflows/ci.yml` `PYREFLY_ERROR_CEILING: "unset"`; frontend E2E/contract jobs `continue-on-error: true`. Needs a measured count from a real CI run.

### TG-A-09 — Stale docs  (Medium, FIXED for two items)
- Migration count/head in `docs/architecture/system.md` (10/`20261004000000` -> 14/`20261008000000`); `docs/CLAIMS.md` C-03 physics versions. NOT checked: frontend STATUS.md contradictions (audit claim unverified by me).

### TG-A-10 — "PATENT" labels in source  (Low, CONFIRMED-OPEN)
- 30 occurrences in `src`/`api` (`grep -i patent`). Unsupported unless a filing exists; rename to neutral wording. If a real filing exists, keep that wording and cite the filing; otherwise rename.

### TG-A-11 — Flat assumed carbon intensity  (Medium, CONFIRMED-OPEN)
- `data/cleaned/carbon_intensity.csv` absent; every run logs the 475 g/kWh fallback and reports `is_real: False`. Carbon-aware conclusions reduce to energy ranking. Needs a licensed time series.

### TG-A-12 — PUE envelope limit not counted per step in evaluation  (Medium, CONFIRMED-OPEN, medium)
- `SAFETY_ENVELOPE` includes a PUE limit; `HARD_CONSTRAINT_METRICS` has no PUE counter. Adding a metric changes the results schema consumed by the frontend; do with a contract update.

## Audit claims I did NOT verify
Forecaster has no baseline; anomaly-threshold leakage; missing `data/cleaned|features|predictions` content (directories exist, content not inspected in depth); PPO candidates unevaluated (consistent with the report's `NOT_EVALUATED`); frontend screenshots/E2E; accessibility; Docker demo startup.

### TG-A-13 — Baseline policies normalise set-points with the legacy 5..15 C range under every physics  (High, FIXED in code by Tasks 1+2; re-tune pending, confidence high)
- Files: `src/baselines/policies.py` (`CHILLED_MIN_C/MAX_C`, `norm_chilled`, `make_action`, all four policies); `src/rl/env.py::CHILLED_WATER_ACTION_RANGE_C` (`legacy-0`: 5..15, `"1"`: 16..25).
- Evidence: under physics 1 a baseline labelled 5/10/12/15 C commands 16.0/20.5/22.3/25.0 C. `tests/test_baselines.py::test_actuator_limits_match_the_environment` failed on the unmodified repo for this reason. Feasibility results remain valid as normalised-action results; the C labels, PID limits and any C-valued report text were wrong.
- Task 1 (done): policies take `physics_version` (default legacy-0, byte-identical actions), read the range from the environment's table, refuse out-of-range set-points instead of clipping, `PIDPolicy.for_physics`, physics-specific default rule set-point (physics 1: 20.5 C, a protocol parameter).
- Task 2 (done): `EvalConfig` set-points are physics-specific and validated at construction (`constant_grid_c`, `default_rule_setpoint_C`; legacy-0 grid and the frozen protocol hash unchanged); tuning, lookup/PID limits, transient-step count and `build_policy` use the physics' own range; configs record `tuning.actuator_range_C` (tuner `baselines-tuner/2`), configs without it are stale; `scripts/eval_policies.py` threads physics.
- STILL OPEN: the user must regenerate the physics-1 protocol, `configs/baselines/*` and the baselines run on their machine (Task 4); until then any previously generated physics-1 configs (tuner /1) are stale by design.
- Also open (Task 3): `src/baseline_recommendation.py`, `src/optimizer_proposals.py`, `api/plugins/optimizer_proposals.py` assume 5..15 C.
- Tests: `tests/test_baseline_physics_ranges.py` (14).

### TG-A-15 — The locked robustness protocol `configs/prereg/prereg_v2.json` registered physics 1 with the legacy 5..15 C grid  (High, FIXED by re-registration, confidence high)
- Found while doing Task 2: its `eval_config` had `physics_version "1"`, `constant_chilled_C [5..15]`, `rule_chilled_C 12.0` (physics 1 reaches 16..25 C), and its `outcome_rules` text predated amendment A1.
- Handling: no evaluation run ever used the old hash `1fe941db…` (checked: no `reports/runs/*/manifest.json` references it), so the repo's own `write_prereg(force=True)` was used. Only four fields changed: `registered_at_utc`, `eval_config` (physics-1 grid 16/18.25/20.5/22.75/25 C, rule 20.5 C), `outcome_rules` (A1 text), `preregistration_sha256` (new `2973cd13…`); the lock file was rewritten; `verify_prereg()` passes. Thresholds, seeds, bootstrap settings and the perturbation manifest are untouched.
- This is an **amendment (A3)** of a locked protocol. It is legitimate only because nothing was evaluated under the old one; review the diff and keep or reject it before Task 9.
