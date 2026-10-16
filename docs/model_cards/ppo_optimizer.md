# Model Card: Cooling Optimizer (PPO)

**Status: the one PPO policy that was ever scored is `quarantined`, and its only score is that it was worse than the rule
baseline. Five newer candidates are `candidate`: trained, not evaluated, not promoted. The only evaluation report on file is a
baselines-only run whose outcome is `NOT_EVALUATED`, with "claim allowed: none".** Nothing here supports calling this optimizer
effective, safe or better than simple controllers. Machine-checked numbers are the `EVIDENCE` lines at the bottom.

## Intended use
A research module that proposes cooling-mode and chilled-water-setpoint actions in the simulator, aiming to reduce
`J = alpha*WUE + beta*(PUE-1) + gamma*carbon` (weights 0.5, 0.3, 0.2). It is not a control system for a real facility. The API
only loads a policy whose registry status is `promoted`; none is.

## Training
`src.optimizer.JointOptimizer`, PPO via stable-baselines3, in `DataCentreEnv` (a live `DigitalTwin` simulation, no historical
dataset). The carbon term uses a flat assumed intensity, not grid data (`models/optimizer/config.json`).

## Results
**Legacy policy (physics `legacy-0`, 3 seeds, 50000 steps each).** Mean PUE improvement versus the rule baseline was **-2.27%**,
that is, worse than the rule. Per seed: -2.37%, -2.17% and -2.27%. The registry's stated 95% interval is +/-0.111 points, but it
is computed with the normal multiplier 1.96 on only 3 seeds; with the t multiplier for 3 seeds (4.303) the half-width from the
registry's own standard deviation (0.098) is about 0.244 points. The sign of the result does not change.
Its environment, reward and safety-envelope versions were never recorded.

**Five v2 candidates (seeds 0 to 4, 98304 steps each).** Trained, exported to a NumPy copy that matches the SB3 policy within
1e-07 on 1000 observations (tolerance 1e-05). That checks the export, not the quality. No evaluation exists for them.

**Baselines-only decision run (60 test scenarios, 30 validation scenarios, no PPO supplied).** Outcome `NOT_EVALUATED`, claim
allowed: none. It does show the benchmark the PPO will have to beat:
- Mean reward per test episode: best constant (15 C, closed loop) -57.88 versus the rule baseline -151.28.
- Mean PUE 1.239 versus 1.275; water per episode about 3,807 L versus 47,476 L; energy about 9,650 kWh versus 9,930 kWh.
- So the rule baseline is a weak comparator: a PPO that beats it by some margin may still lose to a fixed setting.

## Negative and unevaluated results
- The legacy policy is worse than the rule baseline and is quarantined; the SB3 file is not loadable by the API process.
- The v2 candidates have no evaluation and no promotion; the registry notes say evaluation and promotion are a later step.
- Every policy in the baselines run, including the best fixed setting, had the inlet temperature below its minimum for all 288
  steps of every episode, and no constant in the grid did better (288). The simulated comfort constraint is not met by any
  policy tested, so "violation-free" cannot be claimed.
- The pre-registration allows at best the phrase "simulator-validated candidate", and never "AI-optimized".

## Known limitations
- 3 seeds is a minimum, not a statistically strong sample — treat the CI as indicative, not a tight bound. More seeds narrow it
  further if needed.
- Trained against the live `DigitalTwin` simulation directly, not historical facility data — see
  `docs/model_cards/LIMITATIONS.md`.
- No adversarial/out-of-distribution testing (e.g. sensor dropout, extreme weather beyond the training profile's range).
- Physics is `legacy-0` for the legacy policy and `1` for the v2 candidates; results do not transfer between them.
- **Shadow mode**: before this policy controls a real facility, run it in parallel — log its recommended actions without
  applying them, compare against the rule-based baseline over real time — rather than trusting simulation-only PUE numbers.
  `api/services/shadow_mode_service.py` provides the logging primitive; it is not a running comparison service.

## Evidence
- EVIDENCE legacy_status = quarantined | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].status
- EVIDENCE pue_improvement_mean_pct = -2.267707427967431 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].metrics.pue_improvement_mean_pct
- EVIDENCE pue_improvement_std_pct = 0.09835029269020382 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].metrics.pue_improvement_std_pct
- EVIDENCE pue_improvement_ci95_pct = 0.11129383320075262 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].metrics.pue_improvement_ci95_pct
- EVIDENCE seed0_improvement = -2.366168399559505 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].metrics.pue_improvement_per_seed_pct.0
- EVIDENCE seed1_improvement = -2.1694681891051575 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].metrics.pue_improvement_per_seed_pct.1
- EVIDENCE seed2_improvement = -2.2674856952376308 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].metrics.pue_improvement_per_seed_pct.2
- EVIDENCE legacy_timesteps = 50000 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].training_config.json.total_timesteps
- EVIDENCE legacy_alpha = 0.5 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].training_config.json.alpha
- EVIDENCE legacy_beta = 0.3 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].training_config.json.beta
- EVIDENCE legacy_gamma = 0.2 | models/registry.json | artifacts[model_id=ppo_optimizer-20260927T143232Z].training_config.json.gamma
- EVIDENCE v2_status = candidate | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s0].status
- EVIDENCE v2_timesteps = 98304 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s0].params.total_timesteps
- EVIDENCE v2_export_diff_s0 = 8.940696716308594e-08 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s0].metrics.export.equivalence.max_abs_diff
- EVIDENCE v2_export_diff_s1 = 3.725290298461914e-08 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s1].metrics.export.equivalence.max_abs_diff
- EVIDENCE v2_export_diff_s2 = 5.960464477539063e-08 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s2].metrics.export.equivalence.max_abs_diff
- EVIDENCE v2_export_diff_s3 = 8.940696716308594e-08 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s3].metrics.export.equivalence.max_abs_diff
- EVIDENCE v2_export_diff_s4 = 2.9802322387695312e-08 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s4].metrics.export.equivalence.max_abs_diff
- EVIDENCE v2_export_observations = 1000 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s0].metrics.export.equivalence.n_observations
- EVIDENCE v2_export_tolerance = 1e-05 | models/registry.json | artifacts[model_id=ppo-p1-e2-cd2345024-s0].metrics.export.equivalence.tolerance
- EVIDENCE decision_outcome = NOT_EVALUATED | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | decision.outcome
- EVIDENCE decision_claim_allowed = none | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | decision.claim_allowed
- EVIDENCE test_scenarios = 60 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | scenario_sets.test.n
- EVIDENCE validation_scenarios = 30 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | scenario_sets.validation.n
- EVIDENCE best_constant_reward = -57.881079872718104 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.best_constant.total_reward
- EVIDENCE rule_reward = -151.27517508784118 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.rule.total_reward
- EVIDENCE best_constant_pue = 1.2392362863563184 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.best_constant.mean_pue
- EVIDENCE rule_pue = 1.2751064952851843 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.rule.mean_pue
- EVIDENCE best_constant_water_L = 3806.6110121383886 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.best_constant.water_L
- EVIDENCE rule_water_L = 47475.6889 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.rule.water_L
- EVIDENCE best_constant_energy_kwh = 9649.784016285228 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.best_constant.energy_kwh
- EVIDENCE rule_energy_kwh = 9929.62897635071 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.rule.energy_kwh
- EVIDENCE rule_inlet_under_min_steps = 288.0 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.rule.inlet_under_min_steps
- EVIDENCE best_constant_inlet_under_min_steps = 288.0 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | summary_test_mean_per_episode.best_constant.inlet_under_min_steps
- EVIDENCE min_inlet_under_min_any_constant = 288.0 | reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json | selection.min_inlet_under_min_steps_across_constant_grid
- DERIVED normal_multiplier = 1.96 | the multiplier that reproduces pue_improvement_ci95_pct from the std and 3 seeds
- DERIVED t_multiplier_3_seeds = 4.303 | Student t, 0.975 quantile, 2 degrees of freedom
- DERIVED t_halfwidth = 0.244 | t_multiplier_3_seeds x pue_improvement_std_pct / sqrt(3)
