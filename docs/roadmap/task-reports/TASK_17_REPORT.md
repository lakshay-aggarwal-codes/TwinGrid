# Task 17 — ML-002 Re-tune baselines; refresh the registered comparison     Status: PARTIAL (configs, tests, docs done; the run directory is made on your machine, see the runbook)
Base: TwinGrid-main.zip + the Task 5 and Task 7 zips applied     Date: 2026-10-21
Environment: Linux container, Python 3.12.3, numpy 2.5.4, real pytest 9.1.1, ruff; gymnasium installed; NO git, NO TensorFlow, NO torch, NO Postgres.

## Summary
The four baselines were re-tuned on validation scenarios only under `baselines-tuner/3` with PUE counted as a hard constraint. The registered
PPO evaluation was repeated unchanged under the same pre-registration: outcome C again, claim allowed none; the first run is untouched.
No energy-saving claim is made. The committed run directory `baselines-v5` is NOT in this zip: it must carry your real git revision (runbook R1).

## Results
| baseline | validation reward | selected |
|---|---|---|
| rule | -54.8095 | production rule at 20.5 C |
| constant | -36.3247 | 22.75 C, closed_loop |
| lookup | -36.0686 | 5 x 5 bins (25 cells, 7 fallback) |
| pid | -54.1990 | kp=1, ki=0, kd=0, target inlet 26 C |
The PID is no longer degenerate (nonzero proportional gain) but beats the rule by about 1% on validation and stays far behind the constant. No uncertainty estimate was computed for that small gap.
Held-out test (sandbox run baselines-v5, mean reward per episode): constant -36.3272, lookup -36.0675, pid -54.2422, rule -54.8517.
Registered PPO comparison (rerun_t17): outcome C; selected seed 2; summary and decision identical to `full_0fcafef9d28fd539`; per-scenario values differ by at most 9.3e-10. The registered comparator remains `best_constant`; the lookup table is reported as extra context and does not change the decision rule.

## Acceptance checklist
- Configs `/3`: met (all four; `evaluation.json` unchanged).
- Tests green: met for the targeted suites (263 passed, 1 skipped) with a local `baselines-v5` present; the two tests that read that run pass on your machine after runbook R1.
- Old runs untouched and still verify: met in the sandbox (no existing run directory modified); the registered first PPO run was not overwritten (new directory).
- No energy-saving claim: met (C-08 row and model card say outcome C, claim allowed none).
- Model Passport text: NOT updated (`src/model_passport.py` and `models/registry.json` are outside this card's files; they still say "not evaluated").

## Changed files
configs/baselines/{constant,lookup,pid,rule}.json (re-tuned), configs/baselines/evaluation.json (included, byte-identical);
reports/policy_evaluation_physics1/rerun_t17/** (new); docs/CLAIMS.md (C-08 row); docs/model_cards/ppo_optimizer.md (new section + 12 EVIDENCE lines);
tests/test_baselines.py (SHIPPED_RUN -> baselines-v5); tests/test_task19_optimizer_rules.py, tests/test_recommendation_ranges.py, tests/test_task5_hard_constraint_set.py
(these three depended on the old shipped PID/rule; they now set their own parameters; one new test pins the shipped configs to the current rule);
docs/roadmap/ML-002_RUNBOOK.md, docs/roadmap/task-reports/TASK_17_REPORT.md

## Commands run (sandbox)
- `python -m src.baselines.cli tune` (about 9 min): wrote the configs; log shows validation-only sweeps
- `python -m src.baselines.cli run --run-id baselines-v5 --check-determinism` then `verify baselines-v5`: PASS, 1 warning (no git, revision unknown)
- `python -m src.policy_evaluation run` (numpy candidates, new --out): outcome C
- targeted pytest (test_baselines, test_pue_hard_constraint, test_repro_framework, test_recommendation_ranges, test_task5_hard_constraint_set, test_task19_optimizer_rules): 263 passed, 1 skipped
- test_task31_model_cards, test_task20_docs_consistency: pass
- full backend suite, `-m "not postgres"`, with vs without this task (Task 5 + 7 applied in both): 50 failed / 3644 passed vs 54 failed / 3640 passed; 81 collection errors in both (TensorFlow/torch absent). Failure sets diffed: nothing new fails with this task; 4 tests were fixed (3 in test_baselines, 1 register test)
- ruff check on the changed tests: clean; ruff format on the two I reformatted: clean

## Pre-existing failures observed (same with and without this task)
test_artifact_gate (22), test_anomaly_detector (6), test_load_harness (4), test_facility_migration (4), test_task22_register_consistency (3), test_api_runtime_without_torch (2), test_api_routes_smoke (2), and one each in telemetry_ingest, task1_plugins, task18_security_review, t23_carbon_aqueduct_contracts, runtime_fanout, ig05_utilisation_unit, gitignore_source_dirs. Many are the sandbox's missing TensorFlow/torch; I did not diagnose each.
`tests/test_baselines.py` already fails `ruff format --check` before this task; left unformatted to keep the diff small.

## Not run / blocked
Real git revision on the run (runbook R1); Postgres tests; frontend; the CRLF/lock-hash behaviour on Windows.

## Decisions and defaults used
Tuned with the default pre-registration, default search spaces and seeds. `evaluation_document` records the repo-relative directory, so the tune ran with the default `--out`. The PPO re-run went to a new directory because `write_results` silently overwrites a folder with the same scenario-set id.

## Requested cross-task changes
Model Passport / registry text still says "not evaluated"; update when the owner of `src/model_passport.py` and `models/registry.json` next edits them.
`verify` fails a committed run on `code_revision` as soon as HEAD moves; consider recording that as an expected state for historical runs (Task 7 follow-up).

## New limitations or risks
Sandbox numpy 2.5.4 vs your 2.5.3: config floats may differ in the last digits if you re-tune locally; the selection is deterministic.

## Next tasks unblocked
18/19 (if TensorFlow is available). The registered comparison now rests on current-tuner baselines.
