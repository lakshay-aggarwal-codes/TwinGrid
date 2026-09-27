# ADR 003: PPO (reinforcement learning) over a simpler control policy

## Status
Accepted, with caveats this ADR states plainly rather than glossing over.

## Context
Cooling control needs to pick a cooling mode + chilled-water setpoint to
minimize `J = alpha*WUE + beta*(PUE-1) + gamma*carbon` subject to a hard
safety constraint (outlet temp under `OUTLET_TEMP_MAX`). Two real
alternatives existed: a rule-based/heuristic controller (already built,
`DigitalTwin.select_cooling_mode`), or a classical control approach (e.g.
MPC — model-predictive control), or PPO.

## Decision
PPO via stable-baselines3, trained against a live `DigitalTwin` simulation
environment (`DataCentreEnv`).

## Consequences — stated honestly, not as marketing

- **This was NOT a clear win by default.** Before the Phase 0 physics fix,
  PPO beat the rule-based baseline by only ~0.6% PUE — because the
  chilled-water-setpoint action had no effect on the reward at all (see
  `docs/model_cards/ppo_optimizer.md` and the Phase 0 COP fix). A
  reinforcement-learning approach is only worth its complexity if the
  action space actually has exploitable structure a simpler policy
  can't reach; that wasn't true here until the physics bug was fixed.
- Even after the fix, the rule-based heuristic already captures most of
  the cooling-mode decision correctly (same signals: outside temp, water
  stress) — PPO's real edge is specifically in riding the
  chilled-water setpoint as close to the safety constraint as the reward
  allows, a genuinely harder-to-hand-tune multi-objective trade-off.
- **MPC was not implemented or benchmarked against.** For a system with a
  known, differentiable-ish physics model (which this twin has), MPC is a
  legitimate alternative that wasn't ruled out by evidence, only by
  scope/time. If PPO's advantage over the rule-based baseline turns out
  to be marginal even after more seeds/training, MPC is the next
  comparison worth making before investing further in the RL approach.
- PPO's black-box-ness costs interpretability the rule-based approach
  doesn't have — shadow mode (Phase 2) exists specifically to build
  evidence before trusting it unsupervised in a real facility.
- 3-seed statistical evaluation (Phase 2) is the minimum needed to say
  anything about PPO's improvement being real rather than noise; treat
  any single-run PUE-improvement number (including ones from before this
  ADR) with suspicion.
