# Task 9 (roadmap): score the PPO candidates under the physics-1 protocol: PASS 1

(Named `Task9_ppo_evaluation_REPORT.md`: `Task9_REPORT.md` is the earlier API-reference task.)
**No PPO result exists yet. Nothing here says whether PPO is better, equal or worse than the baselines.**

## Inspected (from the uploaded zip)
| Question | Finding | Evidence |
|---|---|---|
| Do candidates exist? | Yes: 5 (seeds 0-4), status `candidate`, never evaluated | `models/candidates/ppo/ppo-p1-e2-cd2345024-s{0..4}/`, `reports/runs/ppo-train-cd2345024-20261006T032326Z/` |
| Trained for which environment? | env v2, physics `1`, reward v2, action semantics 2, envelope v2, shield v1, 98 304 steps, weights 0.5/0.3/0.2 | each `policy_spec.json` `env_contract`, manifest `training_config` |
| Do versions equal the current code? | Version strings: yes (`src/versions.py`: 2/2/2/2/1). Observation/action **schema hashes**: NOT checked here (needs gymnasium, absent in the sandbox); checked by the loader on your machine | `tests/test_numpy_candidate_loader.py::test_shipped_candidates_record_...` |
| Loadable by the harness? | **No.** `src.policy_evaluation.load_candidates` reads only `<dir>/seed_<n>` SB3 saves via `JointOptimizer.load`; `train_ppo.py` writes NumPy exports. `models/optimizer_candidates` (the CLI default) does not exist. | `src/policy_evaluation.py::load_candidates`, `scripts/train_ppo.py` |
| Is the physics-1 protocol current? | **No.** `reports/policy_evaluation_physics1/PREREGISTRATION.json` is `schema_version` 1 and its outcome-rule text predates amendment A2 (PUE hard constraint, Task 6). The config hash is unaffected, the registered text is. `run_episode` already counts `pue_over_max_steps`. | Task 6 report "You must repeat Task 4's human steps" |
| Which protocol scores PPO? | `python -m src.policy_evaluation` (A/B/C outcome, 5 seeds, 30 validation + 60 test scenarios, 3 stress families). `scripts/eval_policies.py` (T30 robustness, `prereg_v2`) is a separate gate and is NOT part of this task. | decision recorded here, not changed |

## Harness fix delivered (code only, no results)
- `src/rl/candidate_loader.py` (numpy + stdlib only): admits a NumPy candidate only if file SHA-256s match its manifest, its recorded environment contract (versions + observation/action schema hashes + physics) equals the CURRENT code, reward weights equal the registered ones, observation size matches, and there is exactly one candidate per registered training seed. Otherwise it raises `CandidateLoadError` and says "retrain". It never repairs or relaxes.
- `src/policy_evaluation.py`: `load_numpy_candidates_for`, CLI `run --candidate-format numpy [--model-id-prefix ...]`; the results get a `candidate_provenance` block (model ids + file hashes). Default behaviour (`joint-optimizer`) unchanged. Protocol, seeds, scenarios, tolerances and decision rules are untouched.
- Tests: `tests/test_numpy_candidate_loader.py`, 9 cases (accept; stale contract x3; weights; tampered file; missing/unregistered/duplicate seed; obs size; shipped candidates' version constants and file hashes).

## Tests run
Sandbox (Linux, numpy 2.5.3, no pytest/torch/gymnasium available; pip has no index): the 9 new tests passed under a minimal pytest-shim runner, `ruff check` clean, new files `ruff format` clean, `src/policy_evaluation.py` compiles. NOT run: the existing test suite, anything needing gymnasium/torch/SB3, the evaluation itself, your machine.

## Not decided here / forbidden to change after seeing results
Decision rules, seeds, scenario sets, tolerances (all frozen in the registration). If a candidate is stale the loader refuses; the fix is retraining under the registered recipe, not editing the contract.

## Pass 2 will contain
Outcome (A/B/C) and the sentence `claim_allowed` permits; paired differences with 95% intervals vs `rule` and `best_constant`; per-constraint violation counts (outlet, inlet-over, inlet-under, PUE-over); which candidate seed validation selected and why; the carbon caveat (flat 475 g/kWh assumption, `is_real: False`); and, if PPO loses or violates constraints, that stated first.
