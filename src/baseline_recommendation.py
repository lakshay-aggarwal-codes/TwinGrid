"""Best-available baseline controller recommendation (Task 19).

Reads the stored baseline configs (``configs/baselines/rule.json``, ``pid.json``), refuses any that is infeasible,
malformed or tuned against different code (``check_lineage``), ranks the rest by the validation reward the tuner STORED
in the config (higher is better), and asks the winner's own policy for a setpoint. Nothing is tuned or learned here.

What the ranking means: it ranks the controllers on the simulated validation scenarios they were tuned on. It does not
say either one is better for any facility, and it is not an evaluation against PPO.

Set-point scale (Task 3). A policy returns a NORMALISED action in [0, 1]; the environment that tuned and evaluated it
turns that into degrees C with the per-physics actuator range (``policies.actuator_range_C``: legacy-0 5..15 C, physics
1 16..25 C). This module does the same, with the physics recorded in the config's lineage (``check_lineage`` has already
proved it equals the physics the API twin runs). So the degrees C returned here are the degrees C the evaluation
EXECUTED for the same action, and the twin the API predicts with consumes degrees C directly. It used to convert with the
legacy 5..15 C range under every physics, which reported 12 C for an action the evaluation ran at 22.3 C.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.baselines import config as bc
from src.baselines.policies import actuator_range_C
from src.optimizer import COOLING_MODES
from src.versions import LEGACY_PHYSICS_VERSION

CANDIDATES = ("pid", "rule")  # an exact tie goes to the LATER entry: the simpler rule controller
RANKING_NOTE = (
    "Ranked by the validation reward stored in each baseline's config (higher is better), measured on simulated "
    "validation scenarios. It is not an evaluation on this facility and not a comparison with PPO."
)


def _denormalise(action: Any, physics_version: str) -> tuple[float, str]:
    """(degrees C the environment executes for ``action`` under ``physics_version``, cooling mode)."""
    lo, hi = actuator_range_C(physics_version)
    chilled = lo + float(action[0]) * (hi - lo)
    mode = COOLING_MODES[int(max(0, min(len(COOLING_MODES) - 1, round(float(action[1]) * 3))))]
    return round(chilled, 3), mode


def _to_policy_scale(current_c: float, physics_version: str, policy_physics_version: str) -> tuple[float, bool]:
    """A real current set-point (C, physics ``physics_version``) expressed in the units the policy's own parameters use.

    The policy's degrees are those of ``policy.physics_version``. They equal the real degrees when it matches the
    config's physics; a config built on the legacy 5..15 scale but tuned under physics 1 is mapped through the
    normalised position, exactly as the evaluation mapped it. A current value outside the actuator range is clipped to
    it (the plant cannot be commanded there); the second return value says whether that happened.
    """
    lo, hi = actuator_range_C(physics_version)
    clipped = not lo <= current_c <= hi
    fraction = (min(max(current_c, lo), hi) - lo) / (hi - lo)
    plo, phi = actuator_range_C(policy_physics_version)
    return plo + fraction * (phi - plo), clipped


def _stored_reward(cfg: dict[str, Any]) -> float | None:
    result = cfg.get("tuning", {}).get("result", {})
    value = result.get("validation_reward") if isinstance(result, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _setpoint(
    cfg: dict[str, Any],
    *,
    outside_temp: float,
    water_stress: float,
    current_chilled_c: float,
    inlet_temp_c: float | None,
) -> dict[str, Any]:
    physics = str(cfg["lineage"]["physics_version"])
    policy = bc.build_policy(cfg)
    policy_physics = str(getattr(policy, "physics_version", LEGACY_PHYSICS_VERSION))
    state = {"outside_temp": outside_temp, "water_stress": water_stress}
    basis = "the stored rule set-point and the production cooling-mode rule"
    clipped = False
    if cfg["name"] == "pid":
        if inlet_temp_c is None:
            # No measured inlet: the PID's operating point (its nominal set-point), not a control step.
            policy.initial_setpoint_C = policy.nominal_setpoint_C
            policy.reset()
            chilled, mode = _denormalise(
                policy.act(None, {**state, "inlet_temp": policy.target_inlet_C}),  # error 0 -> nominal set-point
                physics,
            )
            basis = "the PID nominal set-point (no inlet temperature was supplied) and the production cooling-mode rule"
        else:
            # one control step, starting from the current set-point
            policy.initial_setpoint_C, clipped = _to_policy_scale(current_chilled_c, physics, policy_physics)
            policy.reset()
            chilled, mode = _denormalise(policy.act(None, {**state, "inlet_temp": inlet_temp_c}), physics)
            basis = "one PID step from the current set-point at the supplied inlet temperature, and the production rule"
            if clipped:
                basis += (
                    f" (the current set-point was outside the physics-{physics} actuator range and was clipped to it)"
                )
    else:
        chilled, mode = _denormalise(policy.act(None, state), physics)
    if policy_physics != physics:
        basis += (
            f"; this config's set-points are on the physics-{policy_physics} scale and are converted to the "
            f"physics-{physics} actuator range exactly as the evaluation executed them"
        )
    lo, hi = actuator_range_C(physics)
    return {
        "chilled_water_temp_C": chilled,
        "cooling_mode": mode,
        "basis": basis,
        "physics_version": physics,
        "actuator_range_C": [lo, hi],
    }


def recommend(
    root: Path,
    *,
    outside_temp: float,
    water_stress: float,
    current_chilled_c: float,
    inlet_temp_c: float | None = None,
) -> dict[str, Any]:
    """``{"selected": {...} | None, "considered": [...], "note": str}``; ``selected`` is None if none is usable."""
    considered: list[dict[str, Any]] = []
    usable: list[tuple[float, int, dict[str, Any], dict[str, Any]]] = []
    for order, name in enumerate(CANDIDATES):
        row: dict[str, Any] = {"name": name, "usable": False, "reason": None, "validation_reward": None, "status": None}
        try:
            cfg = bc.load_config(bc.config_path(name, root), name)
            bc.validate(cfg, name)
            row["status"] = cfg["status"]
            row["validation_reward"] = _stored_reward(cfg)
            if cfg["status"] != "feasible":
                row["reason"] = f"config status is {cfg['status']}"
            else:
                bc.check_lineage(cfg)
                if row["validation_reward"] is None:
                    row["reason"] = "the config stores no validation reward, so it cannot be ranked"
                else:
                    bc.build_policy(
                        cfg
                    )  # a set-point the policy cannot hold must skip THIS config, not fail the request
                    row["usable"] = True
                    usable.append((row["validation_reward"], order, cfg, row))  # later in CANDIDATES wins a tie
        except bc.BaselineConfigStale:
            row["reason"] = "tuned against different code or scenarios than the running ones; re-tune it"
        except bc.BaselineConfigError:
            row["reason"] = "the config is missing or malformed"
        except ValueError:
            row["reason"] = "the config's set-points are outside the actuator range its policy accepts; re-tune it"
        considered.append(row)

    selected = None
    if usable:
        reward, _, cfg, row = max(usable, key=lambda t: (t[0], t[1]))
        selected = {
            "name": cfg["name"],
            "validation_reward": reward,
            "tuner_version": cfg["tuner_version"],
            "config": f"{bc.CONFIG_DIR}/{cfg['name']}.json",
            **_setpoint(
                cfg,
                outside_temp=outside_temp,
                water_stress=water_stress,
                current_chilled_c=current_chilled_c,
                inlet_temp_c=inlet_temp_c,
            ),
        }
    return {"selected": selected, "considered": considered, "note": RANKING_NOTE}
