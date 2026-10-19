# TwinGrid final readiness assessment (Task 22)

Date of assessment: 2026-10-19. Tree assessed: `TwinGrid-main_1.zip` (contains Tasks 1-21 reports, Task 15 and Task 18 changes applied, no `.git`).
Method: I re-checked each register item by reading the code, reading the committed artifacts, and running tests. I did not rely on earlier reports. No code was changed.

## 1. Verdict

**Ready to present as a simulator-only research prototype whose headline result is a negative one. Not ready to be described as validated, calibrated, or as saving energy.**

What the evidence supports:
- The evaluation harness is internally consistent: executed physics is recorded and checked, all counted safety limits (outlet, inlet over/under, PUE) must be zero, and the one physics-1 evaluation on file (`reports/policy_evaluation_physics1/full_0fcafef9d28fd539`) gives outcome **C**, claim allowed **none**.
- In that evaluation no policy (rule, best constant, 5 PPO seeds) breached any safety counter on 60 test scenarios, and a fixed 22.75 C closed-loop setting scored better than every PPO seed.

What it does not support: any statement about a real facility, any energy-saving claim for PPO, any carbon conclusion (carbon is a flat assumed 475 g/kWh), the quoted anomaly F1 0.96, and WCAG compliance.

Open defects I found that you should know about before a viva (details in section 4): the shipped baseline configs were produced by the old tuner (`baselines-tuner/2`, PID has zero gains), the baseline tuner ignores the PUE limit, and the run registry cannot verify older runs.

## 2. Evidence base (what was run, where)

| Run | Environment | Result |
|---|---|---|
| Backend `pytest tests` (full, 111 files) | My sandbox: Linux, Python 3.12.3, **no TensorFlow, no torch/stable-baselines3, no PostgreSQL, no `.git`** | 93 failed, 4534 passed, 80 skipped, 1 xfailed, 11 errors, 643.84 s |
| Backend, your latest log `t7_tests_2.txt` | Windows, Python 3.12.10 | 13 failed, 610 passed, 1 skipped, 3 deselected (**624 tests, not the full suite**) |
| Frontend `vitest` | My sandbox, Node 22 | 163 files, 1991 passed, 10 skipped, 0 failed |
| Frontend `tsc --noEmit` | same | 16 errors (unchanged since Task 15's baseline) |
| Frontend `eslint` | same | 0 errors, 3 warnings (`lint:ci` has `--max-warnings 0`, so it fails) |
| Playwright login-screen axe (Task 15, your machine) | Windows | 3 of 3 pass after the contrast fix |

The 93 sandbox failures are **not all real defects**. 22 are `test_artifact_gate.py`, 14 `test_error_contract.py` (its route-discovery script found no routes here; the same failure appeared in the previous tree), plus TensorFlow-dependent anomaly tests, `.git`-dependent tests and database-dependent tests. I did not diagnose each of the 93. What I can say: 12 failures reproduce in both my run and your own log, so they are not sandbox artefacts: `test_pue_hard_constraint` (1), `test_recommendation_ranges` (4), `test_task19_optimizer_rules` (4), `test_repro_framework` (2), `test_t23_carbon_aqueduct_contracts` (1 of your 2). Your log has 13 failures; one, `test_t23...ws_payload_carries_carbon_and_water_labels_fallback`, did not fail for me.

## 3. Register re-verification

Status words: VERIFIED-FIXED (code and tests/artifacts checked), PARTIAL, STILL-OPEN, RESOLVED-BY-REMOVAL, NOT-RE-MEASURED.

| ID | Register said | Now | Evidence (checked in this tree) |
|---|---|---|---|
| TG-A-01 evaluation vs executed physics | FIXED | **VERIFIED-FIXED** | `PhysicsMismatchError` raised at `src/policy_evaluation.py:352`; `physics_version_executed` is written to results (`:746`) and present in the committed `results.json` (`1`). `tests/test_audit_regressions.py` passes in my run. |
| TG-A-02 inlet under-min tolerated | FIXED | **VERIFIED-FIXED** | `HARD_CONSTRAINT_METRICS` = outlet, inlet-over, inlet-under, PUE (`:113`); decision requires all zero (`:629-633`). Committed results: every policy has 0 in all four counters (I summed them from `per_scenario_test`). |
| TG-A-03 physics v2 KeyError in RL | FIXED (guard) | **VERIFIED-FIXED (guard); v2 RL still unsupported** | `UnsupportedPhysicsVersionForRL` in `src/rl/env.py:97`; RL supports the versions in `CHILLED_WATER_ACTION_RANGE_C` only (legacy-0 and 1). |
| TG-A-04 lineage vs tuning physics | FIXED | **VERIFIED-FIXED** | `assert_eval_physics_matches_lineage` in `src/baselines/config.py:61`; configs record `physics_version "1"`, `actuator_range_C [16, 25]`. |
| TG-A-05 "optimized" twin not equivalent | CONFIRMED-OPEN | **RESOLVED-BY-REMOVAL** | `src/digital_twin_optimized.py` no longer exists; `tests/test_physics_v1_invariants.py:773` asserts its absence; `PERFORMANCE_OPTIMIZATION.md` explains the retirement. |
| TG-A-06 false performance claims | FIXED in docs | **PARTIAL / NOT-RE-MEASURED** | The false "45 s -> 0.003 s" text is now quoted only as retracted. I did not run any benchmark. |
| TG-A-07 stale baseline configs | CONFIRMED-OPEN | **PARTIAL (see N-01)** | Configs were regenerated for physics 1 (env version 2, range 16-25 C), but all four carry `tuner_version baselines-tuner/2` while code is `/3`. `tests/test_baselines.py` fails on exactly that (`'baselines-tuner/2' == 'baselines-tuner/3'`). |
| TG-A-08 CI type gate red | CONFIRMED-OPEN | **PARTIAL** | `PYREFLY_ERROR_CEILING` is now `"881"` (was `unset`). Frontend E2E/contract jobs are still `continue-on-error: true` (`ci.yml:290, 378`). I did not run CI. |
| TG-A-09 stale docs | FIXED for two items | **VERIFIED for migrations** | 14 revisions, head `20261008000000` in `alembic/versions` and in `docs/architecture/system.md:80`. Frontend `STATUS.md` contradictions: not checked. |
| TG-A-10 "PATENT" labels | CONFIRMED-OPEN | **MOSTLY FIXED** | One occurrence remains in Python source: `src/optimizer.py:361` key `"patent_objective"`. Renaming a result key may affect consumers; I did not check. |
| TG-A-11 flat carbon | CONFIRMED-OPEN | **STILL-OPEN** | `data/cleaned/` holds only a README; your own 2026-10-19 evaluation log shows the 475 g/kWh fallback warning. Every committed result has `is_real: false`. |
| TG-A-12 PUE not counted | CONFIRMED-OPEN | **PARTIAL (see N-02)** | Harness counts `pue_over_max_steps` and results schema is 2. The baseline tuner's feasibility list `_ENVELOPE_METRICS` (`src/baselines/tuning.py:64`) still omits it; `tests/test_pue_hard_constraint.py::test_the_metric_is_registered_and_a_hard_constraint` fails in my run and in yours. |
| TG-A-13 baseline range assumption | FIXED in code; re-tune pending | **PARTIAL** | Policies/configs use 16-25 C under physics 1. But `test_recommendation_ranges` (4) and `test_task19_optimizer_rules` (4) fail in both environments; I did not isolate the cause (the recommendation returns 20.5 C where the tests expect legacy-scale values such as 10/12 C, so either the tests or the recommendation's physics selection is out of date). |
| TG-A-15 prereg re-registered | FIXED | **VERIFIED** | `configs/prereg/prereg_v2.lock.json` records `2973cd13...`; the prereg's `eval_config` has physics `1` and the 16/18.25/20.5/22.75/25 C grid. The `reports/runs` manifests record different prereg hashes per run (see N-03). |
| TG-A-16 PID degenerate | FIXED in code; re-tune pending | **STILL-OPEN in the shipped artifact** | Code `TUNER_VERSION = /3` searches the PID target. `configs/baselines/pid.json` is `/2`: its candidate list has no target column and the selected gains are kp=ki=kd=0 (validation reward -54.8095 = the rule's). The evaluation decision does not use the PID, so the verdict is not affected. |
| TG-A-17 frontend rejects schema 2 | FIXED | **VERIFIED-FIXED** | `src/evaluation/schema.ts:58` accepts 1 or 2; frontend suite passes. |
| TG-A-18 recommendation form range | FIXED | **VERIFIED-FIXED (frontend)** | Range derived from the server's `setpoint_check`; suite passes. |
| TG-A-19 legacy range in what-if lab | CONFIRMED-OPEN | **STILL-OPEN** | `src/features/what-if-lab/model.ts:31` still `{ min: 5, max: 15 }`. |
| TG-A-20 typecheck + 10 failing tests | CONFIRMED-OPEN | **PARTIAL** | The 10 failing frontend tests now pass (Task 15). Typecheck still 16 errors; eslint 3 warnings. |
| TG-A-21 side-by-side comparison | FIXED (feature) | **VERIFIED** | `PolicyComparison.tsx` + test exist and pass. |

### New findings from this assessment

- **N-01 (High for any PID claim, Low for the verdict).** Shipped baseline configs are `baselines-tuner/2`. The PID in them is the degenerate zero-gain controller from TG-A-16, and `tests/test_baselines.py` fails on the version mismatch. Fix: re-run the tuning with the current code on your machine (the re-tune procedure is described in the Task 4 and Task 4b reports).
- **N-02 (Medium).** The baseline tuner's feasibility check ignores the PUE limit that the evaluation harness enforces. A baseline could be declared "feasible" by the tuner and then fail the harness. `test_pue_hard_constraint` encodes the intended behaviour and fails.
- **N-03 (Medium).** The run registry stores a hash of one shared file (`reports/policy_evaluation_physics1/PREREGISTRATION.json`) in every run manifest, but each run overwrites that file. `baselines-v3` records `3151637...`, `baselines-v4` records `b0acfb1d...` (the current file). Verification of any run except the latest therefore fails (observed in `test_baselines` / registry integrity output). Not a data-integrity breach, but the registry cannot currently prove an older run unchanged.
- **N-04 (Low, documented).** `models/registry.json` still describes the PPO candidates as unevaluated ("nothing trained from this file is evaluated, good, or safe until T30 says so") although a registered evaluation exists. `docs/CLAIMS.md` C-08 already notes this.
- **N-06 (Low-Medium).** `docs/api/` (generated OpenAPI + README) is not in this tree, so `tests/test_task9_api_reference.py` fails ("docs/api/openapi.json is missing"). `docs/CLAIMS.md` C-29 says the reference can be regenerated and is checked by a test; the generator `scripts/gen_api_reference.py` exists but its output is absent. `test_task7_observability.py` also fails on metric names (`telemetry_samples_total`, `background_loop_*` expected but not registered in my environment); cause not isolated.
- **N-05 (Process).** The log you called "latest" covers 624 tests; the repository has about 4,700. No complete test log from your machine exists. The Task 18 regression test file `tests/test_task18_roadmap_security.py` is not in your tree although the code change is.

## 4. Claims: justified vs not justified

Justified by evidence on file:
- C-01/C-02 (simulation only, no real facility connection): code and architecture docs; consistent with everything I read.
- C-08 outcome: committed `results.json` shows outcome C / claim none; PPO selected seed 2 test reward -50.29 vs rule -54.85 (paired difference +4.56, scenario-level 95% CI 3.15 to 5.96) and vs best constant -36.33 (paired difference -13.97, CI -16.42 to -11.52). Seed-level CI against the rule is -3.29 to 3.16, i.e. includes zero.
- C-21/C-22 (rotating refresh tokens, headers, WS tickets, lockout): code read; the security tests I ran pass (`test_task6_security.py` failed once inside the full run but passes alone, so it is order-dependent in my sandbox). Not penetration tested.
- C-28 (single Alembic head): 14 revisions checked.
- C-04 (flat carbon): confirmed.

Not justified, or only with a stated limit:
- **Any claim that PPO saves energy or beats the production rule in general.** On energy PPO used 9,728 kWh vs 9,622 (rule) and 9,414 (best constant); it beat the rule on reward and water, and lost to the constant on everything.
- **C-07, anomaly F1 0.96.** The threshold was tuned on the same rows (Task 12 report); no event-level evaluation has ever been run. Do not quote the number as performance.
- **C-06, forecaster RMSE 0.523 C.** One run, no seed, no baseline.
- **Carbon-aware conclusions.** The carbon series is a flat assumption.
- **"Accessible / WCAG compliant."** Only the login screen was scanned in a browser (3 of 3 pass). No signed-in pages were scanned.
- **"CI is green."** No CI run is on file for this tree (C-34).
- **Performance numbers.** Not re-measured here.

## 5. Top remaining risks (ranked)

1. Headline result is simulator-only with an assumed flat carbon intensity; no calibration to a facility. Any real-world statement is unsupported.
2. PPO's reward advantage over the rule is driven largely by cooling-mode and water behaviour, not set-point control; the best constant is the strong baseline. A reviewer will test this.
3. The tuned baselines in the repo are stale (N-01), so "tuned PID" must not be presented as a comparator.
4. Evidence chain fragility: shared mutable prereg file (N-03), unlocked old runs, no complete test log from your machine (N-05).
5. Safety envelope is evaluated by counted steps in a simulator; zero violations here is not a safety proof.
6. 12 backend tests fail in both environments (section 2): either tests or recommendation logic is out of date.
7. Frontend typecheck red (16) and eslint warnings (3); `lint:ci` fails.
8. Anomaly detector and forecaster figures are optimistic or unbaselined.
9. Security: reviewed, but no penetration test, no dependency audit run (9 npm audit findings on your machine untriaged).
10. The what-if lab still uses the 5-15 C range (TG-A-19).

## 6. The ten hardest viva questions, with truthful answers

1. **Does your PPO controller save energy?** No evidence of that. In the registered physics-1 evaluation the outcome is C: a fixed 22.75 C closed-loop setting scored higher than every PPO seed (-36.33 vs -50.29 for the selected seed). PPO used more energy than both the rule and the constant. The claim allowed is "none".
2. **Then why did you build it?** To test whether learned control beats simple controllers under pre-registered rules. The useful finding is that it does not here, and the harness is what lets you say so honestly.
3. **PPO beat your rule baseline. Is that not a win?** Statistically it did on reward (paired +4.56, CI 3.15 to 5.96 over 60 scenarios) but not across seeds (seed-level CI includes zero), not in every stress family (it lost at stress 0.8), and the rule is not the strongest simple controller. The registered decision compares against the best simple controller that respects the envelope.
4. **You changed the decision rule after seeing results. Why should I trust it?** Amendments A1-A3 are documented. The reports state that no PPO candidate had been scored under the old rule when the rule was tightened and that the prereg was re-registered because no evaluation had used the old hash. That is disclosed, but it remains a change to a locked protocol and a reader may reject it.
5. **How do you know the safety envelope is respected?** Four counters (outlet, inlet over, inlet under, PUE) must be zero for the candidate and for any replacement baseline. They were zero for every policy on 60 test scenarios. That is evidence inside the simulator only; it is not a safety proof, and the baseline tuner does not yet count PUE (N-02).
6. **Is the carbon result real?** No. The series is a flat 475 g/kWh fallback (`is_real: false`). Carbon figures only rank energy.
7. **Your anomaly detector has F1 0.96. What does that mean?** Little. The threshold was chosen on the same rows, faults are synthetic with two fixed types, and no event-level evaluation (delay, false alarms per day) exists. Treat it as a diagnostic.
8. **Is the digital twin accurate?** It is a lumped simulator with engineering parameters, not calibrated to any facility. Its numbers are internally consistent, not validated against measurements.
9. **How was the API secured, and what did you not test?** Rotating single-use refresh tokens, role from the database, lockout, body-size limits, WebSocket tickets, SSRF-guarded webhooks, run caps. Not tested: penetration testing, dependency CVEs, behaviour under real Postgres concurrency (the refresh-race fix was tested on SQLite only).
10. **Do your tests pass?** Frontend: yes (1991 passed, typecheck red). Backend: not on the full suite. In my environment 93 fail, most because TensorFlow, torch, a database and git are absent; 12 fail in your environment as well and are real until fixed. Your latest log covers only 624 of about 4,700 tests.

## 7. What was NOT done

I did not run: CI, TensorFlow/PPO/anomaly tests, Postgres tests, the Docker demo, any benchmark, the signed-in Playwright sweep, `pip-audit`, a re-evaluation or re-tuning, or a diagnosis of each of the 93 sandbox failures. The register's "audit claims I did not verify" list (forecaster baseline, anomaly leakage in the shipped artifact, dataset contents, screenshots, Docker) remains unverified except where stated above.
