# Physics v2 — dynamic lumped-capacitance model

**Level (roadmap 13.1): dynamic twin. UNCALIBRATED.**
Explicit thermal-energy and actuator state, published parameters. It is not calibrated, not validated against any facility, not high-fidelity, and has no per-rack or per-aisle behaviour.

Code: `src/physics/params.py` (parameters), `src/physics/v2.py` (equations). Selected with `PHYSICS_VERSION=2`; `PHYSICS_VERSION=1` is the rollback. `physics_version = "2"`, and `physics_params_hash` is part of the physics identity and of every manifest.

## State

| State | Unit | Meaning |
|---|---|---|
| `T_room` | °C | Bulk room and equipment temperature. The only energy-storing state. |
| `T_in`, `T_out` | °C | Server inlet and outlet air temperature (first-order lag, no energy storage). |
| `T_chw_applied` | °C | Chilled-water setpoint actually in force (rate limit plus first-order lag). |
| `mode_applied` | — | Cooling mode the physics actually used. |
| `water_cum` | L | Cumulative evaporated water. |

Inputs per step: utilisation (0–1), outside temperature, humidity (%), requested cooling mode, requested chilled-water setpoint. Humidity is an input only; there is no humidity state.

## Equations

- Energy balance: `C_th · dT_room/dt = Q_it − Q_cool`
- Cooling: `Q_cool = min(capacity(ambient, humidity, mode), UA · (T_room − T_sink))`, clamped to ≥ 0
- Sink: `T_sink = T_chw_applied` (chiller modes) or ambient (free air)
- IT heat: `Q_it = P_max · (idle + (1 − idle) · utilisation)`
- Capacity: design capacity (`capacity_margin · max_it_power_kw` unless `capacity_design_kw` is set), derated by `capacity_derate_per_c` per °C of heat-rejection temperature above `capacity_derate_start_c`, floored at `capacity_min_fraction`. The rejection temperature is the dry bulb shifted toward the wet bulb by the mode's evaporative share, using the Stull (2011) wet-bulb approximation.
- COP: the v1 functional form (load, outside-temperature, humidity and chilled-water terms), every coefficient from `PhysicsParams`. Cooling electrical power = `Q_cool / COP`.
- Actuator: `delta = (1 − exp(−dt/τ_chw)) · (requested − applied)`, with `|delta| ≤ chw_rate_limit_c_per_5min · dt / 300` enforced exactly.
- Air path: `T_in` and `T_out` relax toward their targets with `α = 1 − exp(−dt/τ_air)`. The room reaches the inlet only once the coil is saturated at capacity.
- Water: `share = min(1, f_evap(mode) · warm_factor(T) · wet_bulb_factor(T, RH))`; `water = share · (Q_cool + P_cooling) · dt · 3.6e6 / latent_heat`. A per-step rate plus a running counter; no basin or blowdown.

## Integration and step size

Semi-implicit Euler: implicit in the UA term, so the linear coil branch is unconditionally stable. The capacity-limited branch applies a constant `Q_cool` over the step (exact). `T_in`, `T_out` and `T_chw` use the exact exponential for a constant target.

`dt = SIM_STEP_SECONDS` (default 300 s) is checked by `check_step_stability`. It must satisfy `dt ≤ min(3600 s, max_dt_over_tau · C_th/UA)`. With the default parameters τ_room = 900 s, so the limit is 3600 s. A larger `dt` raises `PhysicsStabilityError`. The remaining risk at large `dt` is accuracy (first order), not stability.

By construction `C_th · (T_room' − T_room) = (Q_it − Q_cool) · dt`; the residual is reported per step as `closure_residual_kj`.

## Parameters

All values are PROPOSED engineering values. Those marked "v1" are the v1 numbers verbatim; the rest are published guesses, not fitted to any facility. `PhysicsParams` is frozen and validated (finite, in range). `params_hash()` is a SHA-256 over the canonical JSON of every field, so integer 1 and float 1.0 hash the same.

| Group | Parameter (default) |
|---|---|
| IT load (v1) | `max_it_power_kw` 500, `idle_power_fraction` 0.4 |
| Air path (v1) | `air_flow_base_m3_s` 8, `air_flow_full_load_m3_s` 20, `tau_air_min` 10, `chw_approach_c` 2, `inlet_supply_floor_c` 18, `free_air_fan_heat_c` 1, `free_air_ineffective_above_c` 12 |
| Thermal (v2) | `thermal_capacitance_kj_per_k` 22500, `coil_ua_kw_per_k` 25, `max_dt_over_tau` 4 |
| Actuator (v2) | `chw_rate_limit_c_per_5min` 2, `tau_chw_min` 2 |
| Capacity (v1) | `capacity_margin` 1.10, `capacity_design_kw` None, `capacity_derate_start_c` 35, `capacity_derate_per_c` 0.01, `capacity_min_fraction` 0.2 |
| COP (v1) | `cop_free_air` 8, `cop_closed_loop` 4.5, `cop_evaporative` 3.5, `cop_hybrid` 4, `cop_load_derate` 0.15, `cop_outside_derate_start_c` 20, `cop_outside_derate_per_c` 0.01, `cop_min` 0.5, `cop_chw_reference_c` 12, `cop_chw_lift_per_c` 0.02, `cop_chw_bonus_floor` 0.5, `cop_humidity_reference_pct` 40, `cop_humidity_derate_per_pct` 0.005 |
| Water (v1) | `latent_heat_j_per_kg` 2.26e6, evaporative fractions 0 / 0.8÷30 / 0.8 / 0.4 (free air / closed loop / evaporative / hybrid), `water_warm_reference_c` 15, `water_warm_factor_per_c` 0.02 |
| Humidity (v2) | `humidity_reference_pct` 50, `wet_bulb_factor_min` 0.25, `wet_bulb_factor_max` 2 |

## Relation to v1

With constant inputs and `Q_it` below capacity, v2 settles at the v1 steady state (same `T_in`, `T_out`, cooling power, PUE, water) when humidity equals `humidity_reference_pct`. `tests/test_physics_v2.py` checks this to a relative tolerance of 1e-6 (plus 1e-9 absolute). If that test fails, v2 has silently changed the economics: stop and use `PHYSICS_VERSION=1`.

Above capacity, v1 gives a finite algebraic inlet offset while v2 integrates an ever-warming room. This is a deliberate difference: an overloaded plant has no steady state.

## Not modelled

- Per-rack and per-aisle airflow and recirculation (one well-mixed room, one server air stream)
- Compressor dynamics (COP is static; mode changes are instantaneous)
- Storage tanks (no thermal storage, no chilled-water loop volume)
- Electrical distribution losses (UPS, PDU, transformers; total = IT + cooling plant only)
- Basin and blowdown (water = evaporated heat only; no make-up, drift or concentration cycles)
- Equipment ageing (fouling, fan and chiller degradation)
- Weather forecasting (ambient and humidity are inputs for the current step only)

## Allowed and disallowed claims

Allowed: "Dynamic lumped-capacitance simulator with published parameters; uncalibrated."
Not allowed: "calibrated", "validated against a facility", "high-fidelity", any per-rack or per-aisle behaviour.
