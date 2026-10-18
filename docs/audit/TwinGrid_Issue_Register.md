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
