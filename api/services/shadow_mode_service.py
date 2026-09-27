"""Shadow-mode logging for the PPO cooling optimizer.

Before trusting a PPO policy to actually control a facility, the standard
practice is to run it in parallel: log what it *would* have done, without
applying it, and compare against the rule-based baseline over real time.
This module is the logging primitive for that -- record_comparison() reads
the live twin's current state, computes both PPO's action and the rule-based
action for it, and appends one entry to a JSONL log. It does NOT apply
either action to the live twin, and it does NOT run on its own schedule --
call it from wherever the product wants a shadow sample (a cron-style task,
an admin endpoint, a periodic call alongside the live broadcast loop). See
docs/model_cards/ppo_optimizer.md for why this exists and what's still
missing (a scheduled loop + a comparison report).

File-based (JSONL), not a new DB table: avoids an untested Alembic
migration for what's currently an opt-in diagnostic feature, not a
product surface with its own query needs yet.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from api.services import live_broadcast_service
from api.services.twin_service import get_twin
from src.digital_twin import DEFAULT_CHILLED_WATER_TEMP_C
from src.optimizer import COOLING_MODES, DROUGHT_OVERRIDE_MODE, DROUGHT_THRESHOLD, OBS_RANGES, _denormalise, _normalise

logger = logging.getLogger(__name__)

SHADOW_LOG_PATH = Path("logs/shadow_mode.jsonl")


def _build_obs(state: Any, water_stress: float) -> np.ndarray:
    """Same 9-feature observation DataCentreEnv._get_obs() builds, from the
    live twin's current DataCentreState instead of the training env's
    internal state -- so PPO sees a real snapshot, not a simulated one."""
    r = OBS_RANGES
    hour = state.timestamp.hour + state.timestamp.minute / 60.0
    return np.array(
        [
            _normalise(hour, *r["hour"]),
            _normalise(state.server_utilisation, *r["utilisation"]),
            _normalise(state.outside_temp_C, *r["outside_temp"]),
            _normalise(state.server_inlet_temp_C, *r["inlet_temp"]),
            _normalise(state.server_outlet_temp_C, *r["outlet_temp"]),
            _normalise(state.it_power_kw, *r["it_power"]),
            _normalise(state.wue, *r["wue"]),
            _normalise(state.pue, *r["pue"]),
            _normalise(water_stress, *r["water_stress"]),
        ],
        dtype=np.float32,
    )


def _ppo_action(optimizer: Any, obs: np.ndarray, water_stress: float) -> dict[str, Any]:
    action, _ = optimizer._model.predict(obs, deterministic=True)
    chilled = _denormalise(float(np.asarray(action).flat[0]), 5.0, 15.0)
    mode_idx = int(np.clip(round(np.asarray(action).flat[1] * 3), 0, 3))
    mode = COOLING_MODES[mode_idx]
    if water_stress > DROUGHT_THRESHOLD:
        mode = DROUGHT_OVERRIDE_MODE
    return {"chilled_water_temp_C": chilled, "cooling_mode": mode}


def record_comparison(optimizer: Any) -> dict[str, Any] | None:
    """One shadow sample: current live state -> {ppo_action, rule_based_action},
    appended to SHADOW_LOG_PATH. Returns the logged entry, or None if the
    optimizer isn't loaded (nothing to shadow yet).
    """
    if optimizer is None or optimizer._model is None:
        logger.warning("Shadow mode: no trained optimizer available, skipping")
        return None

    twin = get_twin()
    state = twin.state
    water_stress = live_broadcast_service._water_stress_state

    obs = _build_obs(state, water_stress)
    ppo_action = _ppo_action(optimizer, obs, water_stress)

    # Rule-based baseline never adjusts the chilled-water setpoint (see
    # run_scenario()'s default action dict in notebooks/train_all.py) --
    # only picks a cooling mode.
    rule_based_mode = twin.select_cooling_mode(state.outside_temp_C, water_stress)
    rule_based_action = {
        "chilled_water_temp_C": DEFAULT_CHILLED_WATER_TEMP_C,
        "cooling_mode": rule_based_mode.value,
    }

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": {
            "outside_temp_C": state.outside_temp_C,
            "server_utilisation": state.server_utilisation,
            "pue": state.pue,
            "wue": state.wue,
            "water_stress": water_stress,
        },
        "ppo_action": ppo_action,
        "rule_based_action": rule_based_action,
        "actions_agree": ppo_action["cooling_mode"] == rule_based_action["cooling_mode"],
    }

    SHADOW_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SHADOW_LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def summarize(limit: int = 500) -> dict[str, Any]:
    """Read the last `limit` shadow-log entries and summarize agreement
    between PPO and the rule-based baseline -- the actual comparison
    report the roadmap asks for, built from whatever record_comparison()
    has logged so far."""
    if not SHADOW_LOG_PATH.exists():
        return {"n_samples": 0, "agreement_rate": None, "message": "No shadow-mode samples logged yet."}

    lines = SHADOW_LOG_PATH.read_text().splitlines()[-limit:]
    entries = [json.loads(line) for line in lines if line.strip()]
    if not entries:
        return {"n_samples": 0, "agreement_rate": None, "message": "No shadow-mode samples logged yet."}

    agree = sum(1 for e in entries if e["actions_agree"])
    return {
        "n_samples": len(entries),
        "agreement_rate": agree / len(entries),
        "period": {"from": entries[0]["timestamp"], "to": entries[-1]["timestamp"]},
    }
