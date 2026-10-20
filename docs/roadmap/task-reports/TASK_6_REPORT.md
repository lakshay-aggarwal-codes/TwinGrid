# Task 6 — SEC-001 Artifact gate for SB3 loading + registry truth          Status: PARTIAL
Base: TwinGrid-main.zip (no git history; baseline tag made locally; owner's working copy not seen)   Date: 2026-10-20
Environment: Python 3.12.3 (repo pins 3.12.10), pytest 9.1.1, ruff 0.6.9, numpy 2.5.4, pandas 3.0.6, gymnasium 1.4.0,
stable-baselines3 2.9.0 installed WITHOUT torch (no torch/TensorFlow, no Postgres, no Node). A recording stand-in for
`stable_baselines3` is used in the new tests (test double, only in tests).

## Summary
`JointOptimizer.load` no longer calls `PPO.load`. It now runs the contract checks, then `loaders.authorize` over `config.json`
and `ppo_model.zip` (status, SHA-256/size, compatibility, format allow-list), re-reads the config from the verified file, and
only then calls `loaders.load_sb3_zip_training_only`. `grep PPO.load` over `src api scripts` now matches only
`src/artifacts/loaders.py`. The five PPO candidate entries in `models/registry.json` no longer say they were never evaluated.
PARTIAL because 12 tests in `tests/test_artifact_gate.py` still fail for reasons outside this card (below).

## Acceptance checklist
- `grep -rn "PPO.load" src api scripts` only in `src/artifacts/loaders.py` -> MET (`grep` output: loaders.py lines 5 and 481).
- Gate suite green -> NOT MET: 12 failed / 96 passed in the file before the last test was added (see counts); all 12 fail on baseline
  too and are listed below. The two failures this card owns (`test_no_pickle_or_unsafe_loader_exists_outside_the_loaders_module`,
  `test_joint_optimizer_load_is_refused_in_the_api_profile`) are fixed.
- Registry suite green -> `tests/test_artifact_integrity.py` has no failures; no `tests/test_model_registry*.py` exists in this tree.
- Checks not weakened -> MET. No test was skipped, loosened or deleted. Stale tests were re-pointed to where the code now lives
  and still assert the same facts (see Decisions).
- Step 4 negative tests (api refuses SB3; unauthorised path; manifest hash mismatch) -> MET, plus quarantined, config tamper,
  verify-off-still-refuses, contract-before-gate, evaluator path.
- Step 5 registry text + C-08 agreement -> MET for the registry file; the C-08 row's last sentence is now partly stale (Requested changes).

## Changed files
- `src/optimizer.py` — `JointOptimizer.load` only.
- `models/registry.json` — for the 5 `ppo-p1-e2-*` entries: `metrics.null_reasons.evaluation_ref` and `metrics.claim` text. `evaluation_ref`
  stays `null` (nothing was promoted); hashed `training_config` untouched (changing it would invalidate its sha256).
- `tests/test_artifact_gate.py` — new T6 tests; stale tests re-pointed.
- `docs/roadmap/task-reports/TASK_6_PLAN.md`, `TASK_6_REPORT.md`.

## Commands run (this environment)
- `pytest tests/test_artifact_gate.py tests/test_artifact_integrity.py -q` baseline: 22 failed, 106 passed, 4 skipped.
- same, after: 12 failed, 127 passed, 4 skipped.
- `pytest tests/test_t20_envelope_carbon_reach.py tests/test_t23_carbon_aqueduct_contracts.py tests/test_policy_evaluation.py`: 4 failed, 125 passed, before and after (missing `data/cleaned/weather_open_meteo.csv`).
- `pytest tests/test_task18_explain_passport.py tests/test_task20_docs_consistency.py tests/test_optimization_service.py tests/test_numpy_policy.py tests/test_task19_optimizer_rules.py`: 6 failed, 94 passed, 5 skipped, identical before and after.
- `ruff check .` pass; `ruff format --check .` 388 files already formatted (ruff 0.6.9).

## Pre-existing failures observed (all also fail on baseline)
- 10 in the registry-CLI group: `test_quarantine_appends_history_and_never_alters_prior_entries`, `test_transition_rules`,
  `test_promote_requires_integrity_compat_api_format_and_an_evaluation`, `test_required_audit_failure_exits_nonzero_and_leaves_the_registry_unchanged`,
  `test_a_commit_failure_after_the_write_is_reported_as_audit_failure`, `test_audit_row_describes_the_transition`,
  `test_unreachable_database_is_detected_by_the_real_backend`, `test_list_and_dry_run`, and the three `test_migration_*`
  (9 distinct names above plus `test_migration_quarantines...`; 11 total with the next line). Cause: the tests patch
  `cli._audit_backend` / `cli.AUDIT_TIMEOUT_S`, which `scripts/registry_cli.py` no longer has (it takes an `audit=` callable).
  The tests also assume a "required audit" mode the script's docstring says it does not have, so this needs an owner decision.
- `test_shipped_scalers_are_json_and_equal_the_legacy_pickles_when_both_are_present`: `models/anomaly/scaler.joblib` and
  `models/forecaster/scaler.joblib` are checked in. Not deleted here (not a Task 6 file).
- Not in the gate suite: `test_t23_*` (3), `test_t20_*` (1), `test_task18_explain_passport::test_severity_rule_matches_the_pipeline_rule`,
  `test_task19_optimizer_rules` (5).

## Not run / blocked
- `tests/test_t27_env_v2.py` (imports torch) — exercises `JointOptimizer.load` contract rejection. Run: `py -3.12 -m pytest tests/test_t27_env_v2.py -q`.
- Real `PPO.load` of a real SB3 zip under `ARTIFACT_PROFILE=training` — only a test double was used here.
- Full suite, frontend, Postgres jobs.

## Decisions and defaults used
- Order inside `load`: config read + envelope/contract asserts first (existing tests in `test_t20`/`test_t27` expect those errors for
  unregistered directories), then the gate, then a re-read of the verified config, then the loader.
- Stale tests re-pointed, same assertions in spirit: the four `_sabotage_*_version` helpers set the constant to the value it
  already had (a no-op) and now set a different value; schema sabotage and the cadence/schema source checks now target `src/rl/env.py`
  where `ACTION_SCHEMA`, `_BASE_OBS_SCHEMA` and `INTERVAL_MIN` live. `test_joint_optimizer_load_is_refused_in_the_api_profile` used a
  config with no contract, so it hit the envelope error first; it now uses a real-contract artifact.
- `evaluation_ref` kept `null`; evidence cited by path in the text.

## Requested cross-task changes
- Task 17: `docs/CLAIMS.md` C-08 last sentence ("registry entries and the Model Passport still carry older 'not evaluated' text") is now
  partly stale; `scripts/train_ppo.py` lines ~287 and ~337 still write the old "not evaluated ... T30" strings for new candidates;
  each registered `training_config.description` still says "until T30 says so" (hashed, so it needs re-registration).
- Task 21: `twin-stream-insight-main/src/features/explainability/fixtures/passport.json` carries the old claim_boundary text.
- Owner of `src/policy_evaluation.py` / `scripts/eval_policies.py`: call `loaders.enter_training_profile()` at start-up. Until then run
  the evaluator with `$env:ARTIFACT_PROFILE="training"` (and `$env:ARTIFACT_VERIFY="off"` for unregistered scratch `seed_<n>` directories).
- Owner of `scripts/registry_cli.py`: decide the audit behaviour, then align the 11 registry-CLI tests.
- Task 2 / 27: decide whether to `git rm` the two checked-in `scaler.joblib` files.

## New limitations or risks
- `JointOptimizer.load` can no longer load the legacy `models/optimizer` policy (quarantined) even in the training profile.
- Small window between hash verification and the read by SB3 (same as the other loaders); mitigated by hashing, not eliminated.
- An SB3 zip is still a pickle container: a registered, hash-matching hostile file would still execute in a training process.

## Next tasks unblocked
- Task 17 and Task 21 (both listed Task 6 as a prerequisite); both still need Tasks 5 and 7.
