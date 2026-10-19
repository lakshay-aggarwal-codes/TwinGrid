# Task 13 (roadmap): physics v2 in the RL environment: DESIGN ONLY, implementation deferred

(Named `Task13_physics_v2_rl_REPORT.md`; `Task13_REPORT.md` is an earlier, different task.)

## Decision
The roadmap marks this task optional and dependent on Tasks 1-6 and 9. Tasks 1-6 are in the uploaded tree. **Task 9 has produced no
result** (no PPO score exists under the physics-1 protocol), so per contract rule 13 the implementation is blocked. The roadmap allows a
design ADR plus a blocker list when the design cannot be completed safely; that is what is delivered.

## Delivered
- `docs/adr/008-physics-v2-in-the-rl-environment.md`: context, evidence, decision, blocker table B1-B6.
- `scripts/adr008_v2_setpoint_sweep.py`: reproducible physics sweep (no writes; v2 physics only).
- Challenge to the plan: spending a retrain-and-reprotocol cycle on v2 before knowing whether PPO beats the tuned constant (-36.3 validation
  reward vs rule -54.8 in Task 4) is the wrong order. v2 is also uncalibrated, so its extra fidelity buys dynamics, not realism.

## Evidence and where it came from
Sandbox (Linux, Python 3.13.16) run of `src/physics/v2.py` with default parameters: settled inlet = max(18, setpoint + 2); settled outlet = inlet
+ 16.1/19.1/20.7 C at load 0.3/0.7/1.0; 8 steps for the actuator to travel 10 -> 25 C. Not run on your machine, not a facility measurement.

## Tests run
`scripts/adr008_v2_setpoint_sweep.py` executed in the sandbox (output above); `ruff check` and `ruff format` clean on it. No existing test
was run; no environment code was touched; nothing needing gymnasium/torch/SB3 was run.

## Remaining risks
`# RECONSTRUCTED` markers in `src/versions.py` (provenance unverified); shield untested against dynamics; v2 parameters are uncalibrated.
