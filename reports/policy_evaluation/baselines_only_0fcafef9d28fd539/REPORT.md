# PPO decision gate (T8): evaluation report

**Outcome: NOT_EVALUATED**. No PPO candidates were supplied: this is a baselines-only run. No PPO claim can be made from it.
Claim allowed: none.

Physics `legacy-0 (implicit)`. Inputs: synthetic diurnal weather and workload from DataCentreEnv; simulated plant. Carbon curve real: False (flat: True).
Pre-registration `25c4cc68464207f90980eee334f22032c982251afe69f11693f5320c8b1605ac`; scenario-set id `0fcafef9d28fd539` (validation n=30, test n=60).

## Selection (validation only)
- Best constant: `constant[15C,closed_loop]` (validation reward -57.88); rule baseline validation reward -151.3.
- Selected PPO seed: None (highest mean validation reward (not seed order)).
- Lowest inlet-under-min steps per episode reachable by ANY constant: 288.

## Test set, mean per episode
| policy | total_reward | energy_kwh | water_L | carbon_gco2 | mean_pue | mean_wue | outlet_violation_steps | inlet_over_max_steps | inlet_under_min_steps |
|---|---|---|---|---|---|---|---|---|---|
| rule | -151.3 | 9930 | 4.748e+04 | 1.022e+06 | 1.275 | 6.154 | 0 | 0 | 288 |
| best_constant | -57.88 | 9650 | 3807 | 8.893e+05 | 1.239 | 0.4912 | 0 | 0 | 288 |
