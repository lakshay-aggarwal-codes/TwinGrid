# Model Card: Cooling Optimizer (PPO)

## Intended use
Recommends cooling-mode + chilled-water-setpoint actions to minimize
`J = alpha*WUE + beta*(PUE-1) + gamma*carbon`. Backs `/api/optimize`.
Not yet run in production without a human in the loop — see Shadow Mode
below.

## Training
`src.optimizer.JointOptimizer`, PPO via stable-baselines3, environment
`DataCentreEnv` (live `DigitalTwin` simulation, no historical dataset).
Reward weights: alpha=0.5, beta=0.3, gamma=0.2 (config-driven, see
`models/optimizer/config.json`).

As of the Phase-0 physics fix, chiller COP depends on the chilled-water
setpoint for CLOSED_LOOP/HYBRID modes — previously it didn't, which is
why the optimizer had no real second lever beyond cooling-mode selection
(the same choice the rule-based heuristic already makes).

## Evaluation methodology (Phase 2 fix)
Previously reported as a single run's point estimate. `notebooks/train_all.py`
now trains **3 seeds** (0, 1, 2) independently and reports PUE improvement
vs. the rule-based baseline as **mean ± 95% CI** across seeds
(`metrics["pue_improvement_mean_pct"]`/`..._ci95_pct"]` in
`models/registry.json`). The deployed artifact in `models/optimizer/` is
seed 0's run specifically — the mean/CI describes the *training method's*
expected improvement, not a guarantee about that one deployed checkpoint.

## Known limitations
- 3 seeds is a minimum, not a statistically strong sample — treat the CI
  as indicative, not a tight bound. More seeds narrow it further if
  needed.
- Trained against the live `DigitalTwin` simulation directly, not
  historical facility data — see `docs/model_cards/LIMITATIONS.md`.
- No adversarial/out-of-distribution testing (e.g. sensor dropout,
  extreme weather beyond the training profile's range).
- **Shadow mode**: before this policy controls a real facility, run it in
  parallel — log its recommended actions without applying them, compare
  against the rule-based baseline over real time — rather than trusting
  simulation-only PUE numbers. Not yet implemented as a running service in
  this codebase; `api/services/shadow_mode_service.py` (added in this
  pass) provides the logging primitive but needs to be wired into a
  scheduled loop and a comparison report to actually be "shadow mode."
