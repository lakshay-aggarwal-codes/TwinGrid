# PPO decision gate (T8): pre-registration

Registered BEFORE any evaluation run. `preregistration_sha256`: `25c4cc68464207f90980eee334f22032c982251afe69f11693f5320c8b1605ac`
(SHA-256 of the canonical JSON of `config` in `PREREGISTRATION.json`). `run` refuses to start if the file or its hash do not match.

**Scope.** Everything is simulator-only (physics `legacy-0 (implicit)`). Scenario inputs: synthetic diurnal weather and workload from DataCentreEnv; simulated plant.
The best that outcome A can support is the phrase "simulator-validated candidate"; never "AI-optimized".

## Protocol

- Policies, identical scenarios for all: PPO (one candidate per training seed, deterministic action), the **rule baseline**
  (`DigitalTwin.select_cooling_mode` at 12.0 C), and the **best constant** (grid of
  5 chilled-water setpoints x 4 modes, chosen on VALIDATION scenarios only).
- Each scenario is one 288-step (24 h) episode with a fixed environment seed; weather noise, workload,
  initial hour, initial state, timestep and constraints are identical for every policy (verified by an exogenous-trace hash).
- PPO training seeds (5): [0, 1, 2, 3, 4]; seeds 0..99999 are reserved for training.
  Validation seeds start at 100000 (10 per family), test seeds at 200000 (20 per family). All disjoint.
- The deployed candidate is chosen by highest mean VALIDATION reward, not by seed order.
- Statistics: paired differences with a **t-based** 95% CI (df = n-1; exact t quantile, never 1.96).

| family | water stress | seen in training? |
|---|---|---|
| stress_0.0 | 0.0 | yes (in-distribution) |
| stress_0.4 | 0.4 | NO (held-out family) |
| stress_0.8 | 0.8 | NO (held-out family) |

## Metrics

Primary: `total_reward`. Secondary: `energy_kwh`, `water_L`, `carbon_gco2`, `mean_pue`, `mean_wue`.

| metric | better | definition |
|---|---|---|
| `total_reward` | higher | Sum of env reward over the episode (-J minus the outlet penalty): the PPO objective |
| `energy_kwh` | lower | Facility energy, (IT + cooling power) x 5 min, summed |
| `water_L` | lower | Water consumed, summed over the episode |
| `carbon_gco2` | lower | Carbon emitted as accounted by the twin (cooling energy x intensity) |
| `mean_pue` | lower | Mean of per-step PUE |
| `mean_wue` | lower | Mean of per-step WUE |
| `outlet_violation_steps` | lower | Steps with outlet temperature > 45.0 C |
| `inlet_over_max_steps` | lower | Steps with inlet temperature > 27.0 C |
| `inlet_under_min_steps` | lower | Steps with inlet temperature < 18.0 C |

## Outcome rules (PROPOSED in the roadmap; frozen here)

- **A**: Continue under governance: for BOTH the rule baseline and the best constant, (1) the t-based 95% CI of the paired primary-metric difference across TRAINING SEEDS excludes zero in PPO's favour, (2) the same holds across test scenarios for the validation-selected candidate, (3) PPO's mean advantage is positive in every test family, (4) the selected candidate has zero outlet-over-limit and inlet-over-max steps and no more inlet-under-min steps than the rule baseline, (5) no secondary metric is worse by more than the secondary tolerance. Only supports 'simulator-validated candidate'.
- **C**: Replace with a simpler controller: the rule baseline or the best constant, if it has zero outlet-over-limit and inlet-over-max steps on the test set and PPO's mean primary-metric advantage over it is at most the primary tolerance (including the case where PPO is worse). Checked before B.
- **B**: Offline research module only: PPO is not shown to be better than simple controllers, and not shown to be equal.

Tolerances: primary 1% of the simpler controller's |mean reward|; secondary 2%.

Scenario sets: validation `a290e92dcf0037b0` (n=30),
test `b8329f196c910981` (n=60).
