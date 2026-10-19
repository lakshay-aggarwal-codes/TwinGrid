# ADR 008: Physics v2 in the RL environment

## Status
**Proposed. Implementation DEFERRED.** Not started because its precondition is unmet: Task 9 (the first honest PPO A/B/C result under
the physics-1 protocol) has produced no result yet. Building a v2 training stack for a controller that has not yet been shown to beat a
tuned constant setpoint would put effort into the part most likely to change.

## Context
- `DataCentreEnv` supports `legacy-0` and `"1"` only (`RL_SUPPORTED_PHYSICS_VERSIONS`, `src/rl/env.py`); `"2"` raises
  `UnsupportedPhysicsVersionForRL` on purpose. The twin itself runs v2 (`src/physics/v2.py`, `docs/PHYSICS_V2.md`: lumped capacitance,
  explicit `T_room`, actuator rate limit 2 C per 5 min plus first-order lag, `physics_params_hash` part of the identity). v2 is
  **uncalibrated**.
- The physics-1 action range 16..25 C is derived, not tuned: `inlet_min/max (18/27) - approach (2)` (`CHILLED_WATER_ACTION_RANGE_C`).
- `src/versions.py` carries `# RECONSTRUCTED` markers on the v2 label and identity helpers (`physics_identity`,
  `assert_same_physics_identity`). Their provenance must be re-verified before anything is trained on top of them.

## Evidence gathered (simulator only; reproduce with `python scripts\adr008_v2_setpoint_sweep.py`)
Default parameters, `closed_loop`, constant inputs, 2 simulated days. Sandbox run: Linux, Python 3.13.16 (your machine is Python 3.12;
the physics is deterministic, but confirm on yours).

| IT load | chw setpoint 10 / 16 / 20 / 25 / 30 C | settled T_in / T_out (C) |
|---|---|---|
| 0.3 | | 18.0/34.1, 18.0/34.1, 22.0/38.1, 27.0/43.1, 32.0/48.1 |
| 0.7 | | 18.0/37.1, 18.0/37.1, 22.0/41.1, 27.0/46.1, 32.0/51.1 |
| 1.0 | | 18.0/38.7, 18.0/38.7, 22.0/42.7, 27.0/47.7, 32.0/52.7 |

Outside temperature 20 and 35 C gave identical rows. Findings:
1. Steady-state inlet = `max(18, setpoint + 2)`: the v1 derivation of 16..25 C still holds for v2 at steady state.
2. Settled outlet is `T_in + 16.1 / 19.1 / 20.7` at load 0.3 / 0.7 / 1.0, so against the 45 C outlet limit the top of the range is
   infeasible under load (setpoint above about 23.9 C at load 0.7, above about 22.3 C at load 1.0). Same shape of problem as v1; the policy
   has to learn the load-dependent ceiling.
3. The actuator needs 8 five-minute steps (40 min) to travel from the 10 C reset setpoint to a 25 C request. An action's effect is
   delayed and the room integrates; the observation therefore needs `T_room` and the applied setpoint (the latter already exists).

## Decision (design, to be implemented only after Task 9 and the gates below)
1. **Keep `env_version` "2".** Add `"2"` to `CHILLED_WATER_ACTION_RANGE_C` as `(16.0, 25.0)` (same derivation, evidence above).
   legacy-0 and `"1"` rows, hashes and every frozen artifact stay byte-identical (test: compare the three contracts before/after).
2. **Observation for `"2"`:** the 17 v1 features with `room_thermal_C` fed by the real `T_room` (range from the physics, not
   `OBS_RANGES["inlet_temp"]`). This changes `observation_schema_hash` for `"2"` only.
3. **Identity:** `env_contract("2")` and every candidate/baseline/prereg for `"2"` must carry `physics_params_hash`
   (`physics_identity("2", params)`); two parameter sets are two protocols. Absent for legacy-0 and `"1"` (no change to their hashes).
4. **Baselines:** reuse Task 1/2's per-physics range mechanism. Re-derive `initial_setpoint`, rule setpoint, constant grid and PID
   limits for `"2"`; the 40-minute actuator travel means the PID rate limit and the reset setpoint (10 C is outside 16..25) must be
   registered explicitly, not inherited.
5. **Shield and reward:** the safety filter was designed against v1's algebraic inlet. Re-verify it against the dynamic room (a
   setpoint can be safe now and unsafe 3 steps later). Expect a `shield_version` bump for `"2"`. Reward version unchanged unless a normaliser
   range changes.
6. **New protocol, new candidates:** a physics-2 `EvalConfig`/PREREGISTRATION, 5 new training seeds, new baselines run. No physics-1 result
   is carried over.

## Blockers (nothing below is done)
| # | Blocker | Needed |
|---|---|---|
| B1 | Task 9 has no result | run Task 9; if PPO loses to the constant, v2-RL is a research option, not a priority |
| B2 | `# RECONSTRUCTED` provenance in `src/versions.py` | owner confirms the v2 identity code matches the last known-good version; `tests/test_physics_v2.py` green on the owner's machine |
| B3 | Sandbox could not run the RL environment (no gymnasium/SB3/torch) | any v2 env test must run on the owner's machine |
| B4 | Shield not verified against dynamics | design + tests before training |
| B5 | v2 parameters are PROPOSED, uncalibrated (Task 23 needs facility data) | every result must be labelled "uncalibrated simulator" |
| B6 | Cost: 5 seeds x ~100k steps retraining + new baselines tune + new protocol | owner accepts, after B1 |

## Consequences
No code in `src/rl/env.py`, `src/versions.py` or any protocol changes in this ADR. If Task 9 shows PPO beating the strongest baseline
under physics 1, revisit this ADR first; if not, v2 stays twin-only.
