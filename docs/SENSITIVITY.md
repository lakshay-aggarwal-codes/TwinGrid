# Physics sensitivity (Task 10)

**Status: a sensitivity study on SIMULATED data. It is not a calibration and does not say which parameter value is right.**
Every number below comes from the simulator (synthetic diurnal workload and weather, uncalibrated parameters, see
`docs/PHYSICS_V2.md`). It shows how far a few outputs move when one documented parameter is changed, nothing more.

## Method

`python scripts/sensitivity.py` (deterministic: no clock, no random generator; `--help` for options).

* **Parameters.** The 31 physics-1 parameters of `docs/PHYSICS_V2.md` marked (v1), each perturbed **one at a time** to
  -25 %, -10 %, +10 %, +25 % of its default. The default of each is read from the code and a test checks it equals the
  documented value. The safety-envelope limits are never perturbed. Three documented physics-1 parameters are literals
  inside the equations and cannot be perturbed without editing the physics file: `cop_outside_derate_start_c` (20.0),
  `cop_chw_bonus_floor` (0.5), `water_warm_reference_c` (15.0); in physics 2 they are `PhysicsParams` fields and Study 2 covers them.
* **Study 1, physics 1, through the repo's own harness** (`src.policy_evaluation.run_episode`, not modified). Four
  baselines: the production rule and three constant set-points (16 C, 20.5 C, 25 C: low, middle, high of the physics-1
  actuator range) in closed-loop mode. A parameter is changed by temporarily setting the physics module's own
  constant and restoring it afterwards (the restore is tested), so no physics file is edited.
* **Study 2, physics 2, the twin only.** The RL environment refuses physics 2, so the exogenous trace (load, outside
  temperature, water stress per step) of each Study 1 scenario is replayed **open loop** into
  `DigitalTwin(physics_version="2")` with the same four control rules and every numeric `PhysicsParams` field
  perturbed. No safety shield and no feedback act in this replay. A value the model itself rejects would be reported
  as `rejected`, never clipped (none was rejected in this run).
* **Scenarios.** The first 3 scenarios of each of the 3 families (water stress 0.0, 0.4, 0.8) of the **validation**
  split of the shipped protocol: 9 scenarios of 288 steps (one day, 5 min steps). The held-out test split is not used.
  Over these scenarios the outside temperature ranges 14.9 to 29.3 C (mean 22.0 C), utilisation 0.0 to 0.9, and the
  production rule chooses hybrid on 1712 of 2592 steps, closed loop on 864 (the water stress 0.8 family) and
  evaporative on 16; it never chooses free air.
* **Metrics** (mean over the scenarios): mean PUE, energy (kWh per day), water (L per day), mean and maximum server
  outlet and inlet temperature (C), and the number of steps per day that violate the safety envelope (`SAFETY_ENVELOPE`:
  inlet, outlet, PUE), in total and by limit. The full output (JSON, every metric, every policy, every level) is
  produced by `--format json`.

## Where these numbers come from

Run in the sandbox that produced this document, **not on your machine**: Linux x86_64, Python 3.12.3, numpy 2.4.4.
`gymnasium` was not installed there (no network), so a stand-in providing only `gymnasium.Env` and `gymnasium.spaces.Box` was on
the path (it is not part of the repository); the physics, the shield, the baselines and the harness are the repository's
own code. Study 1 and Study 2 were run as two invocations (`--studies physics1`, `--studies physics2`) and merged.
`results_sha256` of the merged numbers (rounded to 9 decimals): `b937a4589d6085dbe9616e3a4994aa28ca7e64246ce0d80567155137ca7cdb6a`. Rerun the script on your
machine and compare the tables first; the last digits can differ across platforms.

## Baselines (unperturbed)

Study 1 (physics 1, harness):

| policy | mean_pue | energy_kwh | water_L | max_outlet_C | max_inlet_C | violation_steps |
|---|---|---|---|---|---|---|
| constant[16C,closed_loop] | 1.235 | 9615 | 461.5 | 38.21 | 18 | 0 |
| constant[20.5C,closed_loop] | 1.217 | 9475 | 454.8 | 42.71 | 22.5 | 0 |
| constant[25C,closed_loop] | 1.202 | 9355 | 449.1 | 47.21 | 27 | 118 |
| rule_baseline | 1.236 | 9620 | 4843 | 42.71 | 22.5 | 0 |

Study 2 (physics 2, twin only, open loop):

| policy | mean_pue | energy_kwh | water_L | max_outlet_C | max_inlet_C | violation_steps |
|---|---|---|---|---|---|---|
| constant[16C,closed_loop] | 1.233 | 9606 | 459.5 | 38.21 | 18 | 0 |
| constant[20.5C,closed_loop] | 1.214 | 9460 | 451.1 | 42.71 | 22.5 | 0 |
| constant[25C,closed_loop] | 1.198 | 9335 | 443.7 | 47.21 | 27 | 118 |
| rule_baseline | 1.233 | 9604 | 4805 | 42.71 | 22.5 | 0 |

The constant 25 C set-point already violates the outlet limit at the default parameters (118 steps per day): it is
listed as a reference, not as a feasible policy.

## Study 1: physics 1, production rule

Change of each metric when the parameter is set to -25 % / +25 % of its default, sorted by the largest change of mean
PUE. The tables for the three constant policies are in `python scripts/sensitivity.py` output.

| parameter | default | mean PUE % (-25% / +25%) | energy % (-25% / +25%) | max outlet C (-25% / +25%) | max inlet C (-25% / +25%) | violation steps (-25% / +25%) |
|---|---|---|---|---|---|---|
| cop_hybrid | 4 | +4.35 / -2.61 | +4.38 / -2.63 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_closed_loop | 4.5 | +1.95 / -1.17 | +1.96 / -1.18 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_chw_reference_c | 12 | -0.92 / +1.02 | -0.93 / +1.03 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_chw_lift_per_c | 0.02 | +0.71 / -0.66 | +0.71 / -0.66 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_load_derate | 0.15 | -0.51 / +0.54 | -0.56 / +0.60 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| capacity_margin | 1.1 | -0.46 / +0.00 | -0.65 / +0.00 | +2.47 / +0.00 | +2.47 / +0.00 | +18.33 / +0.00 |
| idle_power_fraction | 0.4 | -0.18 / +0.18 | -9.15 / +9.20 | -0.09 / +0.09 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_outside_derate_per_c | 0.01 | -0.14 / +0.14 | -0.12 / +0.12 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_evaporative | 3.5 | +0.06 / -0.04 | +0.04 / -0.03 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| chw_rate_limit_c_per_5min | 2 | +0.01 / -0.01 | +0.01 / -0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_humidity_reference_pct | 40 | +0.01 / -0.01 | +0.01 / -0.01 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_humidity_derate_per_pct | 0.005 | -0.00 / +0.00 | -0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| air_flow_base_m3_s | 8 | +0.00 / +0.00 | +0.00 / +0.00 | +0.13 / -0.13 | +0.00 / +0.00 | +0.00 / +0.00 |
| air_flow_full_load_m3_s | 20 | +0.00 / +0.00 | +0.00 / +0.00 | +6.51 / -3.96 | +0.00 / +0.00 | +125.67 / +0.00 |
| capacity_derate_per_c | 0.01 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| capacity_derate_start_c | 35 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| capacity_min_fraction | 0.2 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| chw_approach_c | 2 | +0.00 / +0.00 | +0.00 / +0.00 | -0.50 / +0.50 | -0.50 / +0.50 | +0.00 / +0.00 |
| cop_free_air | 8 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_min | 0.5 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| evap_fraction_closed_loop | 0.0266667 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| evap_fraction_evaporative | 0.8 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| evap_fraction_hybrid | 0.4 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| free_air_fan_heat_c | 1 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| free_air_ineffective_above_c | 12 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| inlet_supply_floor_c | 18 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +4.00 / +0.00 |
| latent_heat_j_per_kg | 2.26e+06 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| max_it_power_kw | 500 | +0.00 / +0.00 | -25.00 / +25.00 | -5.05 / +5.05 | +0.00 / +0.00 | +0.00 / +118.00 |
| tau_air_min | 10 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / -0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| water_warm_factor_per_c | 0.02 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |

Water (litres per day, production rule), not in the table above: `latent_heat_j_per_kg` +33.3 % / -20.0 %,
`evap_fraction_hybrid` -23.8 % / +23.8 %, `water_warm_factor_per_c` -2.9 % / +2.8 %, `evap_fraction_closed_loop`
-0.8 % / +0.8 %, `evap_fraction_evaporative` -0.4 % / +0.0 %.

## Study 2: physics 2, twin only, production rule

Parameters that exist only in physics 2 (or are literals in physics 1), same layout (`water_warm_reference_c` changes water only: +6.5 % / -5.9 % litres per day for the rule):

| parameter | default | mean PUE % (-25% / +25%) | energy % (-25% / +25%) | max outlet C (-25% / +25%) | max inlet C (-25% / +25%) | violation steps (-25% / +25%) |
|---|---|---|---|---|---|---|
| cop_outside_derate_start_c | 20 | +0.88 / -0.46 | +0.86 / -0.40 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| thermal_capacitance_kj_per_k | 22500 | +0.06 / -0.06 | +0.04 / -0.04 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| coil_ua_kw_per_k | 25 | +0.01 / -0.00 | -0.00 / -0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| tau_chw_min | 2 | -0.00 / +0.00 | -0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| cop_chw_bonus_floor | 0.5 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| humidity_reference_pct | 50 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| max_dt_over_tau | 4 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| wet_bulb_factor_max | 2 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| water_warm_reference_c | 15 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |
| wet_bulb_factor_min | 0.25 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 | +0.00 / +0.00 |

For the parameters both physics versions have, the effects agree closely (for example `cop_hybrid` +4.30 % / -2.58 %
mean PUE in physics 2 against +4.35 % / -2.61 % in physics 1). The one clear difference is `capacity_margin` at -25 %:
physics 1 shows +2.5 C on the maximum outlet temperature and +18.3 violation steps per day, physics 2 shows +40.6 C
and +112.0 steps (the two model forms treat load above the cooling capacity differently, see `docs/PHYSICS_V2.md`; I did not investigate
further). The largest per-step energy
closure residual over every physics-2 run is 0.0 kJ.

## What the numbers say (and only that)

1. **Energy follows the load parameters, not the cooling physics.** `max_it_power_kw` at +/-25 % moves daily energy by
   +/-25.0 %, `idle_power_fraction` by +/-9.2 %; both move mean PUE by 0.24 % or less.
2. **PUE of the production rule is set mostly by two COPs**, those of the modes the rule uses: `cop_hybrid` (66 % of
   steps) -25 % -> +4.35 % PUE, +25 % -> -2.61 %; `cop_closed_loop` (33 % of steps) +1.95 % / -1.17 %. Then the chilled
   water reference and lift (about 1 %) and the load derate (about 0.5 %). Every other physics-1 parameter moves PUE by
   less than 0.2 %. In physics 2, `cop_outside_derate_start_c` (a literal in physics 1) moves it +0.88 % / -0.46 %.
3. **Envelope violations depend on the air path and the cooling capacity, not on the COPs.** At -25 %,
   `air_flow_full_load_m3_s` adds +6.5 C to the maximum outlet temperature and 125.7 violation steps per day for the
   rule (0 at the default); `max_it_power_kw` +25 % adds 118 steps; `capacity_margin` -25 % adds 18.3 steps (physics
   1). `inlet_supply_floor_c` -10 % leaves the 16 C constant just under the 18 C inlet minimum on all 288 steps (mean inlet
   17.98 C). In all,
   25 (parameter, level, policy) cells in Study 1 and 26 in Study 2 create violations the
   unperturbed baseline does not have; the lists are in the script output.
4. **Parameters that changed no metric of any policy at any level** in these scenarios: Study 1
   capacity_derate_per_c, capacity_derate_start_c, capacity_min_fraction, cop_free_air, cop_min, free_air_fan_heat_c, free_air_ineffective_above_c; Study 2 adds cop_chw_bonus_floor, max_dt_over_tau, wet_bulb_factor_max, wet_bulb_factor_min. The scenario ranges make this expected for the
   capacity derate (outside temperature never reaches the 35 C start) and the free-air parameters (the rule never
   chooses free air), but that is a property of these 9 scenarios: a hotter or colder day would bring them in.
5. **Room dynamics hardly matter over a day here**: in physics 2 `thermal_capacitance_kj_per_k` +/-25 % moves PUE by
   0.06 %, `coil_ua_kw_per_k` by 0.01 %, `tau_chw_min` by less than 0.01 %.

## What this does not show

* **Nothing about correctness.** None of the parameters is calibrated or validated against a real facility; a parameter
  that matters little here is not thereby well known, and one that matters a lot is not thereby wrong.
* **One at a time.** Interactions are not explored (two parameters moving together can do more or less than the sum).
* **Four levels, +/-25 % at most**; no statement about larger changes or non-linear behaviour outside them.
* **9 synthetic validation scenarios** from the model's own generators (one outside-temperature band, three water-stress
  families, no heat wave, no cold day, no real weather or carbon data). Humidity is not supplied by any scenario, so the
  humidity parameters are exercised only at the twin's default humidity.
* **Rule and constant baselines only.** Not the learned policy, not a tuned controller, and the constants are not tuned.
  A different controller can depend on different parameters.
* **Physics 2 is replayed open loop** without the safety shield or feedback, so its temperatures are what that fixed
  command sequence does, not what a controlled plant would do. Study 1 and Study 2 are therefore not a like-for-like
  comparison of the two physics versions' closed-loop behaviour.
* **Carbon is not a metric** (the grid-intensity series is a fallback in this sandbox, and no conclusion uses it).
* The numbers come from one machine and one run (see above), not from a repeated or cross-platform study.
