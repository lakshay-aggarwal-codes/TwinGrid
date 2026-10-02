"""Deterministic physics scenarios used to freeze and to verify the legacy-0 numerics.

Machine independent on purpose: the carbon curve is injected (not read from
data/cleaned), every twin starts at a fixed timestamp, and nothing here uses
wall-clock time or unseeded randomness. The physics version is selected through
the PHYSICS_VERSION environment variable (honoured by src/versions.py; the
pristine, pre-T7 code simply ignores it).
"""

from __future__ import annotations

import itertools
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from unittest import mock

import numpy as np

CURVE = np.linspace(300.0, 600.0, 24)  # hour-dependent, so a wrong hour lookup is visible
FLAT = np.full(24, 475.0)
START = datetime(2025, 6, 1, 3, 0, 0)

UTILISATIONS = (0.1, 0.5, 0.9)
OUTSIDE_TEMPS = (-5.0, 10.0, 25.0, 40.0)
WATER_STRESSES = (0.0, 0.5, 1.0)
MODES = ("auto", "free_air", "closed_loop", "evaporative", "hybrid")


@contextmanager
def physics_env(version: str, curve: np.ndarray = CURVE):
    """A physics version + an injected carbon curve (patched where digital_twin imported it)."""
    with mock.patch.dict(os.environ, {"PHYSICS_VERSION": version}):
        with mock.patch("src.digital_twin.load_diurnal_carbon_intensity", return_value=(curve, False)):
            yield


def legacy_env(curve: np.ndarray = CURVE):
    return physics_env("legacy-0", curve)


def _clean(state_dict: dict[str, Any]) -> dict[str, Any]:
    out = dict(state_dict)
    out["timestamp"] = out["timestamp"].isoformat()
    return out


def grid_states() -> list[dict[str, Any]]:
    """One step on a fresh twin for the full util x temp x stress x mode grid."""
    from src.digital_twin import CoolingMode, DigitalTwin

    rows = []
    for u, t, s, m in itertools.product(UTILISATIONS, OUTSIDE_TEMPS, WATER_STRESSES, MODES):
        twin = DigitalTwin(start_time=START)
        mode = twin.select_cooling_mode(t, s) if m == "auto" else CoolingMode(m)
        state = twin.step({"utilisation": u, "outside_temp_C": t, "water_stress": s, "cooling_mode": mode})
        rows.append({"inputs": {"u": u, "t": t, "s": s, "mode": m}, "state": _clean(state.to_dict())})
    return rows


def live_sequence() -> list[dict[str, Any]]:
    """20 steps on ONE twin (thermal lag, actuator rate limit, cumulative water)."""
    from src.digital_twin import CoolingMode, DigitalTwin

    twin = DigitalTwin(start_time=START)
    modes = [CoolingMode.CLOSED_LOOP, CoolingMode.EVAPORATIVE, CoolingMode.HYBRID, CoolingMode.FREE_AIR]
    rows = []
    for i in range(20):
        state = twin.step(
            {
                "utilisation": 0.2 + 0.04 * i,
                "outside_temp_C": 5.0 + 1.7 * i,
                "water_stress": 0.05 * (i % 6),
                "cooling_mode": modes[i % 4],
                "chilled_water_temp_C": 6.0 + 0.5 * i,
                "humidity_pct": 40.0 + 2.0 * i,
            }
        )
        rows.append(_clean(state.to_dict()))
    return rows


def whatif_cases() -> list[dict[str, Any]]:
    """api.services.twin_service.compute_whatif on a reduced grid (flat carbon: it starts at wall-clock hour)."""
    from api.services import twin_service

    rows = []
    with mock.patch("src.digital_twin.load_diurnal_carbon_intensity", return_value=(FLAT, False)):
        for u, t, s, m, cw in itertools.product(
            (0.3, 0.9), (5.0, 35.0), (0.0, 0.8), ("auto", "evaporative"), (7.0, 12.0)
        ):
            result = twin_service.compute_whatif(u, t, s, m, cw)
            rows.append({"inputs": {"u": u, "t": t, "s": s, "mode": m, "cw": cw}, "result": result})
    return rows


def env_rollout() -> list[dict[str, Any]]:
    """40 steps of DataCentreEnv (reward, penalty, carbon term, action mapping) with fixed actions."""
    from src.optimizer import DataCentreEnv

    env = DataCentreEnv(seed=3, water_stress=0.2, carbon_intensity_by_hour=CURVE)
    obs, _ = env.reset(seed=3)
    actions = np.random.default_rng(0).uniform(size=(40, 2)).astype(np.float32)
    rows = [{"obs": [float(x) for x in obs]}]
    for a in actions:
        obs, reward, terminated, truncated, info = env.step(a)
        rows.append(
            {
                "obs": [float(x) for x in obs],
                "reward": float(reward),
                "state": {k: (float(v) if not isinstance(v, bool) else v) for k, v in info["state"].items()},
            }
        )
    return rows


def build_all(version: str = "legacy-0") -> dict[str, Any]:
    with physics_env(version):
        data = {"grid_states": grid_states(), "live_sequence": live_sequence(), "env_rollout": env_rollout()}
    with mock.patch.dict(os.environ, {"PHYSICS_VERSION": version}):
        data["whatif"] = whatif_cases()
    return data
