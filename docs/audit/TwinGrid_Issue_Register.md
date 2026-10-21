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

### TG-A-05 — "Optimized" twin is not numerically equivalent  (High, FIXED, resolved by removal, high)
- Files: `src/digital_twin_optimized.py`, `benchmark_performance.py`, `PERFORMANCE_OPTIMIZATION.md`.
- Evidence: on the benchmark inputs max |d outlet| ~ 20 C, max |d PUE| ~ 0.10 vs `DigitalTwin(legacy-0)`. Used only by the benchmark and two tests.
- Done: strict xfail documenting it; benchmark success banner removed; perf doc rewritten. Not done: fix or retire the module.

### TG-A-06 — Performance claims false and unreproducible  (High, FIXED in docs, high)
- Doc claimed 45 s / 3.844 s -> 0.003 s and cited non-existent modules. Measured: main twin ~3.3 ms per simulated day. Single run, one machine; rewritten as indicative only.

### TG-A-07 — Shipped baseline configs stale vs environment v2  (High, PARTIAL, high)
- 6 failing tests in `tests/test_baselines.py` on the unmodified repo: `lineage.environment_version` recorded `1`, code is `2`; `requirements.lock` hash differs.
- Fix requires re-tuning under a physics-1 protocol on the owner's machine (commands in the verification summary). Not done here: artifacts generated in the audit sandbox would carry the sandbox's hashes.

### TG-A-08 — CI type gate deliberately red  (Medium, CONFIRMED-OPEN, high)
- `.github/workflows/ci.yml` `PYREFLY_ERROR_CEILING: "unset"`; frontend E2E/contract jobs `continue-on-error: true`. Needs a measured count from a real CI run.

### TG-A-09 — Stale docs  (Medium, FIXED for two items)
- Migration count/head in `docs/architecture/system.md` (10/`20261004000000` -> 14/`20261008000000`); `docs/CLAIMS.md` C-03 physics versions. NOT checked: frontend STATUS.md contradictions (audit claim unverified by me).

### TG-A-10 — "PATENT" labels in source  (Low, MOSTLY FIXED)
- 30 occurrences in `src`/`api` (`grep -i patent`). Unsupported unless a filing exists; rename to neutral wording. If a real filing exists, keep that wording and cite the filing; otherwise rename.

### TG-A-11 — Flat assumed carbon intensity  (Medium, CONFIRMED-OPEN)
- `data/cleaned/carbon_intensity.csv` absent; every run logs the 475 g/kWh fallback and reports `is_real: False`. Carbon-aware conclusions reduce to energy ranking. Needs a licensed time series.

### TG-A-12 — PUE envelope limit not counted per step in evaluation  (Medium, FIXED in code, medium)
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

### TG-A-16 — The tuned PID baseline is degenerate under physics 1 (zero gains = the rule baseline)  (Medium, FIXED in code by Task 4b; re-tune pending, confidence high)
- Evidence (owner's machine, validation scenarios, `baselines-v3` tuning, all 60 gain sets feasible): best candidate `kp=ki=kd=0`, validation reward -54.8095 = exactly the rule baseline's; reward falls monotonically with `kp` (0.5 -> -54.867, 1 -> -54.896, 2 -> -54.925) and with `kd`.
- Cause (sandbox diagnostic, validation set only, one run, not shipped): the PID's `target_inlet_C` is fixed at 22 C and is not searched. The reward prefers a WARMER inlet (envelope 18..27 C), so any feedback toward 22 C costs reward. With target 24/25/26 C and `kp>0` the PID beats the zero-gain one (e.g. target 26, kp 1: -54.199, 0 violations); target 26 with kp 2 violates the envelope (456 steps), so the search must be bounded by feasibility, as it already is.
- Also: even the best PID stays near -54 because it uses the production MODE rule; the best constant (22.75 C, `closed_loop`) scores -36.32. The cooling-mode choice, not the set-point, dominates the gap on these scenarios.
- Impact: "PID" is not an independent comparator today; the A/B/C decision only uses the rule and best constant, so Task 9 is not blocked.
- Fix (Task 4b, done in code): `pid_target_inlet_C` is searched over the envelope's upper inlet limit minus (5, 3, 2, 1) C = (22, 24, 25, 26) C; `TUNER_VERSION` `/3` (older configs are stale); candidates, the selected target and the search space are recorded; ties resolve to the smaller target. Sandbox scratch run (Linux, validation only, not shipped): PID selected target 26 C, kp=1, validation reward -54.199 vs rule -54.809; 141 of 240 candidates feasible (integral gain > 0 violated the envelope at warmer targets). The search space is not part of the registered protocol hash, so no re-registration is needed; the owner must re-tune and re-run (`baselines-v3`).
- Caveat that remains: the PID uses the production MODE rule, so it stays ~18 reward behind the best constant (-36.32); it is a set-point controller, not a competitor for the constant's mode choice.

### TG-A-17 — Frontend rejected schema-2 evaluation reports and ignored what they say  (High, FIXED by Task 14, confidence high)
- `src/evaluation/schema.ts` accepted `schema_version` 1 only, while the API now serves 1 and 2 (amendment A2): the first new report would have shown as a contract violation. The UI also ignored `hard_constraints` and `selection`, and the API never passed `physics_version_executed`; hard-constraint metrics were plain table columns in policy order.
- Fixed in `twin-stream-insight-main/src/evaluation/*`, `src/components/evaluation/*` and `api/services/evaluation_service.py` (additive passthrough of `physics_version_executed`).

### TG-A-18 — Recommendation form hardcoded the legacy 5..15 C and showed no provenance  (High, FIXED by Task 14, confidence high)
- `optimizer-approvals/model.ts::setpointProblem` rejected any physics-1 recommendation (16..25 C) with "must be between 5 and 15", blocking the sandbox/propose flow for the baseline's own output; the card had no provenance strip, physics or evidence note.
- Fixed with a range derived from `predicted.setpoint_check` (mirrors the server's union), a strip, an evidence note and out-of-range notices.

### TG-A-19 — The legacy 5..15 C assumption remains elsewhere in the frontend  (Medium, FIXED in source)
- `src/features/what-if-lab/model.ts` (`setpointC: { min: 5, max: 15 }`) and the sidebar "Chilled Water Setpoint" slider. Not changed in Task 14 (scope). Follow-up: one shared physics-derived accepted range fed by the backend.

### TG-A-20 — `npm run typecheck` fails on the uploaded frontend (16 errors, 12 files) and 10 vitest tests fail  (Medium, CONFIRMED-OPEN, pre-existing)
- Identical on the pristine upload and after Task 14. Errors are union-narrowing problems in `admin-console`, `capacity`, `carbon-scheduling`, `command-palette`, `economics`, `executive-dashboard`, `maintenance` (e.g. `Property 'error' does not exist on type 'Parsed<string>'`). Failing tests: `registry.test.ts`, `bundleScan.test.ts`, `TwinHeader.test.tsx`, `CommandPalette.test.tsx`, `executive-dashboard/components.test.tsx`, `FacilityInspector.test.tsx`, `LabPage.test.tsx`. `npm run verify` cannot pass today.

### TG-A-21 — No way to put two policies side by side with the hard constraints first  (Medium, FIXED by Task 16 as a feature)
- The evaluation screen listed all policies in one table and the constraint panel (Task 14) was separate; a reader had to cross-reference to see why a candidate was or was not eligible. `PolicyComparison` adds the head-to-head view described in `PROVENANCE_AND_FRESHNESS.md`.
- Open: cross-report comparison (e.g. legacy-0 vs physics-1 baselines) is deliberately NOT offered: it would need equal scenario set, executed physics and carbon basis, and refuse otherwise. Run-registry drill-down (config/seeds of a `reports/runs/*` run) is not linked from the evaluation screen: the evaluation payload carries no run id for it.


## Task 22 re-verification (2026-10-19)

Full table with evidence: `docs/audit/TwinGrid_Final_Assessment.md` (section 3). Summary of status changes against the entries above:

| ID | Status now |
|---|---|
| TG-A-01, -02, -04, -17, -18, -21 | VERIFIED-FIXED |
| TG-A-03 | VERIFIED-FIXED (guard); physics v2 RL still unsupported |
| TG-A-05 | RESOLVED-BY-REMOVAL (`digital_twin_optimized.py` deleted in Task 5) |
| TG-A-06 | PARTIAL, benchmarks not re-measured |
| TG-A-07 | PARTIAL: configs regenerated for physics 1 but `baselines-tuner/2` (code is `/3`); `test_baselines` fails |
| TG-A-08 | PARTIAL: ceiling set to 881; frontend E2E/contract jobs still `continue-on-error` |
| TG-A-09 | VERIFIED for migrations (14, head `20261008000000`); frontend STATUS.md not checked |
| TG-A-10 | MOSTLY FIXED: one occurrence left (`src/optimizer.py:361`, key `patent_objective`) |
| TG-A-11 | STILL-OPEN (flat 475 g/kWh, `is_real: false`) |
| TG-A-12 | PARTIAL: harness counts PUE; baseline tuner `_ENVELOPE_METRICS` does not (N-02) |
| TG-A-13 | PARTIAL: ranges fixed; 8 recommendation tests fail in both environments, cause not isolated |
| TG-A-15 | VERIFIED |
| TG-A-16 | STILL-OPEN in the shipped `configs/baselines/pid.json` (tuner/2, zero gains) |
| TG-A-19 | STILL-OPEN (`what-if-lab/model.ts:31`) |
| TG-A-20 | PARTIAL: the 10 vitest failures are gone (Task 15); typecheck 16 errors, eslint 3 warnings remain |

New entries: N-01 stale shipped baseline configs, N-02 PUE missing from tuner feasibility, N-03 run registry cannot verify older runs (shared mutable `PREREGISTRATION.json`), N-04 stale registry text for PPO, N-05 incomplete test log and missing Task 18 test file, N-06 `docs/api/` missing.


## Reconciliation 2026-10-21 (Task 32): one status per ID

Method: each row was checked against the tree on this date (file present/absent, config contents, workflow text, grep). **No test or
CI run was possible**, so "fixed" means "the code or file shows the fix"; it is not "a test passed today". Earlier sections above are
historical and kept as written.

| ID | Status | Evidence |
|---|---|---|
| TG-A-01 | FIXED (code; test not re-run) | `src/policy_evaluation.py` resolves and passes the physics version; `tests/test_audit_regressions.py` |
| TG-A-02 | FIXED (code; test not re-run) | `HARD_CONSTRAINT_METRICS` in `src/policy_evaluation.py` (three counted limits plus PUE), all required to be zero |
| TG-A-03 | FIXED (guard); physics v2 RL still unsupported | `src/rl/env.py` `UnsupportedPhysicsVersionForRL` |
| TG-A-04 | FIXED (code; test not re-run) | `src/baselines/*` lineage guard |
| TG-A-05 | RESOLVED BY REMOVAL | `src/digital_twin_optimized.py` is absent |
| TG-A-06 | FIXED in docs; benchmarks not re-measured | `PERFORMANCE_OPTIMIZATION.md`; `reports/perf/2026-10/README.md` lists every measurement as not run |
| TG-A-07 | PARTLY FIXED | shipped `configs/baselines/{rule,lookup,constant,pid}.json` are `baselines-tuner/3`, environment 2, physics 1; `test_baselines` result not seen; stored run is `baselines-v4` (older), `baselines-v5` not in tree |
| TG-A-08 | OPEN | `.github/workflows/ci.yml`: `PYREFLY_ERROR_CEILING: "881"` set, but `frontend-e2e` and `frontend-contract` still `continue-on-error: true`; no recorded green run |
| TG-A-09 | FIXED for migrations (15 revisions, head `20261101000000`); frontend `STATUS.md` updated in this task | `alembic/versions/*`; `twin-stream-insight-main/docs/frontend/STATUS.md` |
| TG-A-10 | MOSTLY FIXED | one occurrence left: `src/optimizer.py:361` key `patent_objective` |
| TG-A-11 | OPEN (by design) | `data/cleaned/carbon_intensity.csv` absent; carbon labelled assumed (`src/carbon_label.py`, Task 20) |
| TG-A-12 | FIXED in code; test not re-run | `PUE_METRIC` is in `HARD_CONSTRAINT_METRICS`; `src/baselines/tuning.py` takes `_ENVELOPE_METRICS` from it (so N-02 is closed) |
| TG-A-13 | FIXED in code (Tasks 1, 2, 5 of the earlier series); recommendation tests not re-run | `src/baselines/policies.py`, `tests/test_baseline_physics_ranges.py` |
| TG-A-15 | VERIFIED (re-registration A3) | `configs/prereg/prereg_v2.json`; no run references the old hash |
| TG-A-16 | FIXED in config | `configs/baselines/pid.json`: `selected_gains` kp 1.0, `target_inlet_C` 26.0, status `feasible` (no longer all-zero); the stored demo run `baselines-v4` still shows the old collapse |
| TG-A-17 | FIXED (code) | `twin-stream-insight-main/src/evaluation/*` |
| TG-A-18 | FIXED (code) | `features/optimizer-approvals/model.ts` range derived from the server check |
| TG-A-19 | FIXED in source | `features/what-if-lab/model.ts` has a physics-derived set-point range (`setpointRange.test.ts`); Task 4 report; typecheck not run |
| TG-A-20 | UNVERIFIED | `npm run typecheck` not run in any task of this series; Task 4 report says only a syntax-level check was possible |
| TG-A-21 | FIXED (feature) | `PolicyComparison`; cross-report comparison deliberately not offered |
| N-01 | PARTLY FIXED | see TG-A-07 |
| N-02 | FIXED in code | see TG-A-12 |
| N-03 | OPEN | run registry still cannot verify older runs (shared `PREREGISTRATION.json`); Task 7 added immutable provenance for new runs |
| N-04 | UNVERIFIED | registry text for PPO not re-read in this task |
| N-05 | OPEN | no complete test log for this tree exists |
| N-06 | OPEN | `docs/api/` absent (playbook Task 21 not applied) |
