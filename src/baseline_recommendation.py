"""Best-available baseline controller recommendation (Task 19).

Reads the stored baseline configs (``configs/baselines/rule.json``, ``pid.json``), refuses any that is infeasible,
malformed or tuned against different code (``check_lineage``), ranks the rest by the validation reward the tuner STORED
in the config (higher is better), and asks the winner's own policy for a setpoint. Nothing is tuned or learned here.

What the ranking means: it ranks the controllers on the simulated validation scenarios they were tuned on. It does not
say either one is better for any facility, and it is not an evaluation against PPO.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.baselines import config as bc
from src.baselines.policies import CHILLED_MAX_C, CHILLED_MIN_C
from src.optimizer import COOLING_MODES

CANDIDATES = ("pid", "rule")  # an exact tie goes to the LATER entry: the simpler rule controller
RANKING_NOTE = (
    "Ranked by the validation reward stored in each baseline's config (higher is better), measured on simulated "
    "validation scenarios. It is not an evaluation on this facility and not a comparison with PPO."
)


def _denormalise(action: Any) -> tuple[float, str]:
    chilled = CHILLED_MIN_C + float(action[0]) * (CHILLED_MAX_C - CHILLED_MIN_C)
    mode = COOLING_MODES[int(max(0, min(len(COOLING_MODES) - 1, round(float(action[1]) * 3))))]
    return round(chilled, 3), mode


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
    policy = bc.build_policy(cfg)
    state = {"outside_temp": outside_temp, "water_stress": water_stress}
    basis = "the stored rule set-point and the production cooling-mode rule"
    if cfg["name"] == "pid":
        if inlet_temp_c is None:
            # No measured inlet: the PID's operating point (its nominal set-point), not a control step.
            policy.initial_setpoint_C = policy.nominal_setpoint_C
            policy.reset()
            chilled, mode = _denormalise(
                policy.act(None, {**state, "inlet_temp": policy.target_inlet_C})  # error 0 -> nominal set-point
            )
            basis = "the PID nominal set-point (no inlet temperature was supplied) and the production cooling-mode rule"
        else:
            policy.initial_setpoint_C = current_chilled_c  # one control step, starting from the current set-point
            policy.reset()
            chilled, mode = _denormalise(policy.act(None, {**state, "inlet_temp": inlet_temp_c}))
            basis = "one PID step from the current set-point at the supplied inlet temperature, and the production rule"
    else:
        chilled, mode = _denormalise(policy.act(None, state))
    return {"chilled_water_temp_C": chilled, "cooling_mode": mode, "basis": basis}


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
                    row["usable"] = True
                    usable.append((row["validation_reward"], order, cfg, row))  # later in CANDIDATES wins a tie
        except bc.BaselineConfigStale:
            row["reason"] = "tuned against different code or scenarios than the running ones; re-tune it"
        except bc.BaselineConfigError:
            row["reason"] = "the config is missing or malformed"
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
