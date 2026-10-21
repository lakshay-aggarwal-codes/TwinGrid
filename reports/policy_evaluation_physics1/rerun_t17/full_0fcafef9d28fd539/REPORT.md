# PPO decision gate (T8): evaluation report

**Outcome: C**. A simpler controller (best_constant) is within the primary tolerance of PPO and respects the safety envelope.
Claim allowed: none.

Physics `1` (executed: `1`). Inputs: synthetic diurnal weather and workload from DataCentreEnv; simulated plant. Carbon curve real: False (flat: True).
Pre-registration `fe76f6691857ef267c6fc958fda22f187b8a077110ae3dfc0d9d4e65835d9105`; scenario-set id `0fcafef9d28fd539` (validation n=30, test n=60).

## Selection (validation only)
- Best constant: `constant[22.75C,closed_loop]` (validation reward -36.32); rule baseline validation reward -54.81.
- Selected PPO seed: 2 (highest mean validation reward (not seed order)).
- Lowest inlet-under-min steps per episode reachable by ANY constant: 0.

## Test set, mean per episode
| policy | total_reward | energy_kwh | water_L | carbon_gco2 | mean_pue | mean_wue | outlet_violation_steps | inlet_over_max_steps | inlet_under_min_steps | pue_over_max_steps |
|---|---|---|---|---|---|---|---|---|---|---|
| rule | -54.85 | 9622 | 4851 | 4.571e+06 | 1.236 | 0.631 | 0 | 0 | 0 | 0 |
| best_constant | -36.33 | 9414 | 451.5 | 4.472e+06 | 1.209 | 0.05855 | 0 | 0 | 0 | 0 |
| ppo_seed_0 | -56.24 | 9764 | 4872 | 4.638e+06 | 1.254 | 0.6316 | 0 | 0 | 0 | 0 |
| ppo_seed_1 | -56.3 | 9768 | 4875 | 4.64e+06 | 1.254 | 0.6321 | 0 | 0 | 0 | 0 |
| ppo_seed_2 | -50.29 | 9728 | 3832 | 4.621e+06 | 1.247 | 0.4417 | 0 | 0 | 0 | 0 |
| ppo_seed_3 | -55.7 | 9748 | 4817 | 4.63e+06 | 1.251 | 0.6207 | 0 | 0 | 0 | 0 |
| ppo_seed_4 | -56.06 | 9753 | 4865 | 4.633e+06 | 1.252 | 0.6304 | 0 | 0 | 0 | 0 |

## Paired differences, PPO minus baseline (primary metric, higher is better)
- vs **rule**: across 5 training seeds mean -0.06774, 95% t-CI [-3.291, 3.156]; selected candidate across 60 test scenarios mean 4.558, CI [3.151, 5.965]. Criteria: {'seed_ci_excludes_zero_for_ppo': False, 'scenario_ci_excludes_zero_for_ppo': True, 'advantage_positive_in_every_family': False, 'secondary_within_tolerance': True}
- vs **best_constant**: across 5 training seeds mean -18.59, 95% t-CI [-21.82, -15.37]; selected candidate across 60 test scenarios mean -13.97, CI [-16.42, -11.52]. Criteria: {'seed_ci_excludes_zero_for_ppo': False, 'scenario_ci_excludes_zero_for_ppo': False, 'advantage_positive_in_every_family': False, 'secondary_within_tolerance': False}
- Envelope (selected candidate): {'outlet_violation_steps': 0.0, 'inlet_over_max_steps': 0.0, 'inlet_under_min_steps': 0.0, 'pue_over_max_steps': 0.0, 'rule_inlet_under_min_steps': 0.0, 'ok': True}
