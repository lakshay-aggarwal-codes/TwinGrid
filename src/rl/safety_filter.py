"""The shield (T27, roadmap 13.5): a PURE, VERSIONED function from (state, env action) to executed action.

    a_s  --(SB3: clip to the Box)-->  a_e  --shield(state, a_e)-->  a_x  --> plant (applied via rate limit/lag)

The shield is part of the environment: it is deterministic, identical in training and serving, and does not
touch the policy's log-prob/value (those are computed on the sampled action ``a_s``). Its effect is reported
in ``info`` so the policy can see it (removes the non-Markov defect, F-14).

Action encoding (both components in [0, 1]):  [chilled-water setpoint (normalised), cooling mode / 3].
Rules (SHIELD_VERSION 1):
  1. non-finite components are replaced by a safe default (mid setpoint, closed_loop);
  2. components outside [0, 1] are clipped;
  3. the mode component is snapped to its discrete mode (index / 3) -- what is executed is a discrete mode;
  4. DROUGHT RULE: if ``state["water_stress_scenario"]`` > DROUGHT_THRESHOLD (or is not finite: fail closed),
     the mode is forced to DROUGHT_OVERRIDE_MODE. Triggered by the SCENARIO variable, never the Aqueduct baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from ..versions import SHIELD_VERSION

COOLING_MODES = ["free_air", "closed_loop", "evaporative", "hybrid"]
DROUGHT_THRESHOLD = 0.7
DROUGHT_OVERRIDE_MODE = "closed_loop"
N_MODES = len(COOLING_MODES)
DROUGHT_OVERRIDE_MODE_INDEX = COOLING_MODES.index(DROUGHT_OVERRIDE_MODE)
DEFAULT_SETPOINT_NORM = 0.5
ACTION_DIM = 2

__all__ = [
    "ACTION_DIM",
    "COOLING_MODES",
    "DROUGHT_OVERRIDE_MODE",
    "DROUGHT_OVERRIDE_MODE_INDEX",
    "DROUGHT_THRESHOLD",
    "SHIELD_VERSION",
    "ShieldFlags",
    "mode_index_of",
    "shield",
]


@dataclass(frozen=True)
class ShieldFlags:
    drought_triggered: bool  # rule 4 engaged (scenario above threshold, or not finite)
    mode_overridden: bool  # rule 4 changed the requested mode
    clipped: bool  # rule 2: some finite component was outside [0, 1]
    non_finite_replaced: bool  # rule 1

    @property
    def active(self) -> bool:
        """The shield enforced something (drought rule engaged, clipping, or non-finite replacement)."""
        return self.drought_triggered or self.clipped or self.non_finite_replaced

    def as_dict(self) -> dict[str, bool]:
        return {
            "drought_triggered": self.drought_triggered,
            "mode_overridden": self.mode_overridden,
            "clipped": self.clipped,
            "non_finite_replaced": self.non_finite_replaced,
        }


def mode_index_of(mode_component: float) -> int:
    """Discrete mode index of a [0, 1] mode component (round(c * 3), clipped to 0..3), in float32 like SB3."""
    c = np.float32(mode_component)
    return int(np.clip(round(c * 3), 0, N_MODES - 1))


def shield(state: Mapping[str, Any], a_e: Any) -> tuple[np.ndarray, ShieldFlags]:
    """Pure: returns ``(a_x, flags)``. Same inputs -> same outputs; nothing is read from or written to globals.

    ``state`` must contain ``water_stress_scenario``; ``a_e`` is any array-like of 2 numbers.
    """
    a = np.asarray(a_e, dtype=np.float32).reshape(-1)
    if a.shape != (ACTION_DIM,):
        raise ValueError(f"action must have {ACTION_DIM} components, got shape {np.asarray(a_e).shape}")
    finite = np.isfinite(a)
    non_finite = not bool(finite.all())
    clipped = bool(((a < 0.0) | (a > 1.0))[finite].any())
    out = np.where(finite, a, np.array([DEFAULT_SETPOINT_NORM, DROUGHT_OVERRIDE_MODE_INDEX / 3.0], dtype=np.float32))
    out = np.clip(out, 0.0, 1.0).astype(np.float32)

    idx = mode_index_of(out[1])
    scenario = state["water_stress_scenario"]
    try:
        scenario_f = float(scenario)
    except (TypeError, ValueError):
        scenario_f = math.nan
    triggered = (not math.isfinite(scenario_f)) or scenario_f > DROUGHT_THRESHOLD
    overridden = triggered and idx != DROUGHT_OVERRIDE_MODE_INDEX
    if triggered:
        idx = DROUGHT_OVERRIDE_MODE_INDEX
    out[1] = np.float32(idx / 3.0)
    return out, ShieldFlags(triggered, overridden, clipped, non_finite)
