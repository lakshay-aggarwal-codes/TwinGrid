"""The four deterministic baseline policies (contract 13.8): Rule, Constant, Lookup, PID.

Every policy here is a pure function of what the environment shows it (``state``: hour, utilisation,
outside_temp, inlet_temp, water_stress, ...) plus, for PID only, its own integrator. None reads the
clock, a random generator or the scenario identity, so the same config on the same scenario always
gives the same actions. All of them emit the environment's own normalised action ``[chilled, mode]``
and are bound by the SAME actuator limits: the chilled-water set-point range OF THE PHYSICS VERSION BEING RUN
(``actuator_range_C``: legacy-0 5..15 C, physics 1 16..25 C -- read from the environment's own table), the
plant's per-step rate limit, and the same four cooling modes (the drought override is applied by the
environment itself). A policy that is not told its physics version assumes legacy-0, which keeps every
pre-existing call site and the committed legacy report unchanged.

MPC is NOT implemented (contract 13.8: a perfect-model controller would be an oracle upper bound, not a
deployable baseline).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ..digital_twin import DEFAULT_CHILLED_WATER_TEMP_C, DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP, DigitalTwin
from ..optimizer import COOLING_MODES
from ..rl.env import CHILLED_WATER_ACTION_RANGE_C, assert_rl_supported_physics_version
from ..versions import LEGACY_PHYSICS_VERSION

# The environment maps action[0] in [0,1] linearly onto the chilled-water range of the physics version
# (DataCentreEnv._action_to_control) and rounds action[1]*3 to a mode index. The range is PHYSICS-DEPENDENT:
# a policy must normalise with the SAME range or "12 C" silently becomes some other temperature.
# CHILLED_MIN_C / CHILLED_MAX_C are the LEGACY-0 limits only, kept for backward compatibility; new code must use
# ``actuator_range_C(physics_version)``. Tests pin both to the environment.
CHILLED_MIN_C = 5.0
CHILLED_MAX_C = 15.0
MAX_RATE_C_PER_STEP = DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP
INITIAL_SETPOINT_C = 10.0  # DataCentreEnv.reset() starts the plant at 10 C

PRODUCTION_RULE = "production_rule"


def actuator_range_C(physics_version: str = LEGACY_PHYSICS_VERSION) -> tuple[float, float]:
    """(lowest, highest) chilled-water set-point in C that the environment can command under ``physics_version``.

    Read from ``DataCentreEnv``'s own table, never copied. Raises ``UnsupportedPhysicsVersionForRL`` for a
    version the RL environment cannot run (currently ``2``).
    """
    return CHILLED_WATER_ACTION_RANGE_C[assert_rl_supported_physics_version(physics_version)]


def default_rule_setpoint_C(physics_version: str = LEGACY_PHYSICS_VERSION) -> float:
    """The production rule's chilled-water set-point under ``physics_version`` (a PROTOCOL parameter, not tuned).

    legacy-0: the twin's default (12 C), unchanged. Other versions: the middle of the actuator range, because
    the legacy 12 C lies BELOW physics 1's reachable range (16..25 C) and would otherwise be silently clipped.
    """
    if physics_version == LEGACY_PHYSICS_VERSION:
        return float(DEFAULT_CHILLED_WATER_TEMP_C)
    lo, hi = actuator_range_C(physics_version)
    return (lo + hi) / 2.0


def _check_in_range(celsius: float, physics_version: str, what: str) -> None:
    lo, hi = actuator_range_C(physics_version)
    if not lo <= celsius <= hi:
        raise ValueError(
            f"{what} {celsius:g} C is outside the actuator range {lo:g}..{hi:g} C of physics {physics_version!r}; "
            "it would be silently clipped to a different temperature"
        )


def norm_chilled(celsius: float, physics_version: str = LEGACY_PHYSICS_VERSION) -> float:
    lo, hi = actuator_range_C(physics_version)
    return float(np.clip((celsius - lo) / (hi - lo), 0.0, 1.0))


def norm_mode(mode: str) -> float:
    return COOLING_MODES.index(mode) / 3.0


def make_action(chilled_C: float, mode: str, physics_version: str = LEGACY_PHYSICS_VERSION) -> np.ndarray:
    return np.array([norm_chilled(chilled_C, physics_version), norm_mode(mode)], dtype=np.float32)


class _ProductionModeRule:
    """``DigitalTwin.select_cooling_mode``: the production mode rule (sees outside temperature and water stress)."""

    def __init__(self) -> None:
        self._twin = DigitalTwin()

    def __call__(self, state: dict[str, Any]) -> str:
        return self._twin.select_cooling_mode(float(state["outside_temp"]), float(state["water_stress"])).value


# ----------------------------------------------------------------------------- Constant


@dataclass
class ConstantPolicy:
    chilled_C: float
    mode: str
    name: str = ""
    physics_version: str = LEGACY_PHYSICS_VERSION

    def __post_init__(self) -> None:
        if self.mode not in COOLING_MODES:
            raise ValueError(f"unknown cooling mode {self.mode!r}")
        _check_in_range(self.chilled_C, self.physics_version, "constant set-point")
        if not self.name:
            self.name = f"constant[{self.chilled_C:g}C,{self.mode}]"

    def reset(self) -> None:
        pass

    def act(self, obs: np.ndarray, state: dict[str, Any]) -> np.ndarray:
        return make_action(self.chilled_C, self.mode, self.physics_version)


# ----------------------------------------------------------------------------- Rule


class RulePolicy:
    """The production rule at the twin's default chilled-water set-point. It sees only what the PPO
    observation also carries (outside temperature, water stress)."""

    def __init__(self, chilled_C: float | None = None, physics_version: str = LEGACY_PHYSICS_VERSION) -> None:
        self.name = "rule_baseline"
        self.physics_version = physics_version
        # None -> the physics' own default (legacy-0: 12 C, exactly as before; physics 1: mid-range).
        self._chilled_C = default_rule_setpoint_C(physics_version) if chilled_C is None else float(chilled_C)
        _check_in_range(self._chilled_C, physics_version, "rule set-point")
        self._mode_rule = _ProductionModeRule()

    def reset(self) -> None:
        pass

    def act(self, obs: np.ndarray, state: dict[str, Any]) -> np.ndarray:
        return make_action(self._chilled_C, self._mode_rule(state), self.physics_version)


# ----------------------------------------------------------------------------- Lookup


class LookupPolicy:
    """State-dependent table over (IT utilisation, outside temperature) bins -> one fixed ``(set-point, mode)``.

    ``util_edges`` / ``temp_edges`` are ascending interior bin edges; a value ``v`` falls in bin
    ``bisect_right(edges, v)`` (so each bin is closed on the left, open on the right, and the first and
    last bins are unbounded). ``actions[i][j]`` is the ``(chilled_C, mode)`` for utilisation bin ``i`` and
    temperature bin ``j``. The table is built by ``tuning.tune_lookup`` from validation scenarios only.
    """

    def __init__(
        self,
        util_edges: Sequence[float],
        temp_edges: Sequence[float],
        actions: Sequence[Sequence[tuple[float, str]]],
        name: str = "lookup",
        physics_version: str = LEGACY_PHYSICS_VERSION,
    ) -> None:
        self.physics_version = physics_version
        lo, hi = actuator_range_C(physics_version)
        self.util_edges = [float(e) for e in util_edges]
        self.temp_edges = [float(e) for e in temp_edges]
        if self.util_edges != sorted(self.util_edges) or self.temp_edges != sorted(self.temp_edges):
            raise ValueError("bin edges must be ascending")
        if len(set(self.util_edges)) != len(self.util_edges) or len(set(self.temp_edges)) != len(self.temp_edges):
            raise ValueError("bin edges must be distinct")
        if len(actions) != len(self.util_edges) + 1 or any(len(row) != len(self.temp_edges) + 1 for row in actions):
            raise ValueError("actions must be a (len(util_edges)+1) x (len(temp_edges)+1) table")
        self.actions = [[(float(c), str(m)) for c, m in row] for row in actions]
        for row in self.actions:
            for c, m in row:
                if m not in COOLING_MODES or not lo <= c <= hi:
                    raise ValueError(f"table action ({c}, {m}) is outside the actuator limits")
        self.name = name

    def cell(self, utilisation: float, outside_temp: float) -> tuple[int, int]:
        return bisect.bisect_right(self.util_edges, utilisation), bisect.bisect_right(self.temp_edges, outside_temp)

    def reset(self) -> None:
        pass

    def act(self, obs: np.ndarray, state: dict[str, Any]) -> np.ndarray:
        i, j = self.cell(float(state["utilisation"]), float(state["outside_temp"]))
        chilled, mode = self.actions[i][j]
        return make_action(chilled, mode, self.physics_version)


# ----------------------------------------------------------------------------- PID


@dataclass
class PIDPolicy:
    """Inlet-temperature PID -> chilled-water set-point, with a FIXED mode rule.

    ``error = target_inlet_C - inlet_temp``: an inlet colder than the target means the plant is
    over-cooling, so the set-point is raised (cheaper cooling); an inlet hotter than the target lowers it.
    One control step is one environment step (5 minutes), so gains are per step.

        u = nominal + kp*e + ki*I + kd*(e - e_prev)

    The output is bound by the same actuator limits as every other baseline: clipped to
    [min, max] and rate-limited to ``max_rate`` C per step around the previous output (the plant applies
    the same rate limit, so the controller's memory of its own output stays truthful).

    Anti-windup is *conditional integration*: whenever the output is held back by a limit AND the error
    would push it further into that limit, the integrator is frozen. With ``anti_windup=False`` the
    integrator always accumulates (kept only so tests can show what windup looks like).

    Mode rule (fixed, not tuned): ``production_rule`` (``DigitalTwin.select_cooling_mode``) or a fixed
    cooling-mode name.
    """

    target_inlet_C: float
    kp: float
    ki: float
    kd: float
    nominal_setpoint_C: float = DEFAULT_CHILLED_WATER_TEMP_C
    initial_setpoint_C: float = INITIAL_SETPOINT_C
    min_setpoint_C: float = CHILLED_MIN_C
    max_setpoint_C: float = CHILLED_MAX_C
    max_rate_C_per_step: float = MAX_RATE_C_PER_STEP
    mode_rule: str = PRODUCTION_RULE
    anti_windup: bool = True
    name: str = ""
    physics_version: str = LEGACY_PHYSICS_VERSION
    _integral: float = field(default=0.0, init=False, repr=False)
    _prev_error: float | None = field(default=None, init=False, repr=False)
    _prev_output: float = field(default=0.0, init=False, repr=False)
    _saturated_steps: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not (self.min_setpoint_C < self.max_setpoint_C):
            raise ValueError("min_setpoint_C must be below max_setpoint_C")
        lo, hi = actuator_range_C(self.physics_version)
        if not (lo <= self.min_setpoint_C and self.max_setpoint_C <= hi):
            raise ValueError(
                f"set-point limits {self.min_setpoint_C:g}..{self.max_setpoint_C:g} C must lie inside the plant's "
                f"actuator range {lo:g}..{hi:g} C of physics {self.physics_version!r}"
            )
        if self.max_rate_C_per_step <= 0:
            raise ValueError("max_rate_C_per_step must be positive")
        if self.mode_rule != PRODUCTION_RULE and self.mode_rule not in COOLING_MODES:
            raise ValueError(f"mode_rule must be {PRODUCTION_RULE!r} or one of {COOLING_MODES}")
        if min(self.kp, self.ki, self.kd) < 0:
            raise ValueError("gains must be non-negative")
        if not self.name:
            self.name = f"pid[kp={self.kp:g},ki={self.ki:g},kd={self.kd:g}]"
        self._production = _ProductionModeRule() if self.mode_rule == PRODUCTION_RULE else None
        self.reset()

    @classmethod
    def for_physics(
        cls, physics_version: str, target_inlet_C: float, kp: float, ki: float, kd: float, **overrides: Any
    ) -> "PIDPolicy":
        """A PID whose set-point limits and nominal set-point come from ``physics_version`` (not from legacy-0).

        ``initial_setpoint_C`` stays the plant's frozen reset value (10 C) CLIPPED into the range, exactly as
        ``reset()`` always did: under physics 1 the plant starts below its reachable range and its own rate
        limit walks it up, while the controller's memory starts at the nearest reachable value.
        """
        lo, hi = actuator_range_C(physics_version)
        params: dict[str, Any] = dict(
            nominal_setpoint_C=default_rule_setpoint_C(physics_version),
            min_setpoint_C=lo,
            max_setpoint_C=hi,
            physics_version=physics_version,
        )
        params.update(overrides)
        return cls(target_inlet_C, kp, ki, kd, **params)

    # -- state -------------------------------------------------------------------------------
    def reset(self) -> None:
        """Start of an episode: integrator and derivative memory cleared, output at the plant's start value."""
        self._integral = 0.0
        self._prev_error = None
        self._prev_output = float(np.clip(self.initial_setpoint_C, self.min_setpoint_C, self.max_setpoint_C))
        self._saturated_steps = 0

    @property
    def integral(self) -> float:
        return self._integral

    @property
    def output(self) -> float:
        return self._prev_output

    @property
    def saturated_steps(self) -> int:
        return self._saturated_steps

    # -- control law -------------------------------------------------------------------------
    def setpoint(self, inlet_C: float) -> float:
        """One PID update from a measured inlet temperature; returns the chilled-water set-point (C)."""
        error = float(self.target_inlet_C) - float(inlet_C)
        derivative = 0.0 if self._prev_error is None else error - self._prev_error
        candidate = self._integral + error
        unsaturated = self.nominal_setpoint_C + self.kp * error + self.ki * candidate + self.kd * derivative
        low = max(self.min_setpoint_C, self._prev_output - self.max_rate_C_per_step)
        high = min(self.max_setpoint_C, self._prev_output + self.max_rate_C_per_step)
        output = min(max(unsaturated, low), high)
        held_back = output != unsaturated
        pushes_deeper = held_back and error * (unsaturated - output) > 0.0
        if not self.anti_windup or not pushes_deeper:
            self._integral = candidate
        self._saturated_steps = self._saturated_steps + 1 if held_back else 0
        self._prev_error = error
        self._prev_output = output
        return output

    def act(self, obs: np.ndarray, state: dict[str, Any]) -> np.ndarray:
        chilled = self.setpoint(float(state["inlet_temp"]))
        mode = self._production(state) if self._production is not None else self.mode_rule
        return make_action(chilled, mode, self.physics_version)
