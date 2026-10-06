"""DataCentreEnv, environment v2 (T27, roadmap 13.5): action and observation semantics.

    a_s (policy sample) -> a_e = clip(a_s, 0, 1) (SB3) -> shield(state, a_e) = a_x (executed) -> plant

* ``step(a_e)`` applies the shield internally and reports ``executed_action``, ``shield_active`` and the applied
  setpoint/mode in ``info``.
* The observation (physics v1) adds the applied chilled-water setpoint, the applied mode (one-hot), the previous
  executed action and the room-thermal state, so the shield's and the actuator's effects are observable.
* ``observation_schema_hash`` / ``action_schema_hash`` identify the exact ordered names and ranges.
* legacy-0 physics keeps its frozen 9-feature observation (its goldens must not move).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import gymnasium as gym
import numpy as np

from ..carbon_provider import _a, load_carbon_signal, signal_for_curve  # noqa: F401  (_a re-exported for the shim)
from ..carbon_provider import carbon_basis as _carbon_basis_of
from ..digital_twin import (
    CHILLED_WATER_APPROACH_C,
    OUTLET_TEMP_MAX,
    SAFETY_ENVELOPE,
    CoolingMode,
    DigitalTwin,
    carbon_emissions_gco2,
)
from ..versions import (
    ACTION_SEMANTICS_VERSION,
    ENV_VERSION,
    LEGACY_PHYSICS_VERSION,
    PHYSICS_V1,
    REWARD_VERSION,
    SAFETY_ENVELOPE_VERSION,
    SHIELD_VERSION,
    EnvContractError,
    active_physics_version,
    assert_current_env_versions,
    validate_physics_version,
)
from .safety_filter import (
    COOLING_MODES,
    DROUGHT_OVERRIDE_MODE_INDEX,
    mode_index_of,
    shield,
)

DROUGHT_OVERRIDE_MODE_INDEX_NORM = DROUGHT_OVERRIDE_MODE_INDEX / 3.0

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# PATENT: Cooling mode enumeration — maps discrete control to physical systems
# 0=free_air, 1=closed_loop, 2=evaporative, 3=hybrid
# -----------------------------------------------------------------------------
# COOLING_MODES / DROUGHT_* live in src/rl/safety_filter.py (single definition, used by the shield).

# NOTE: no per-mode COP/evaporation-rate dicts and no thermal/water constants
# here anymore. All physics (COP, water, thermal lag) now runs through the
# single authoritative src/digital_twin.py DigitalTwin -- see
# DataCentreEnv._step_physics(). This file only configures that twin and
# converts between its DataCentreState and this environment's obs/action.
INTERVAL_MIN = 5
MAX_IT_POWER_KW = 500.0
IDLE_FRAC = 0.4
AIRFLOW_M3_S = 8.0
OUTLET_MAX = OUTLET_TEMP_MAX  # re-exported from digital_twin, not a second copy
DEFAULT_SIM_STEP_SECONDS = INTERVAL_MIN * 60  # A-1: 300 s

# Chilled-water setpoint range the agent's [0, 1] action maps onto, PER PHYSICS VERSION.
#  * legacy-0: 5-15 C (frozen). Under legacy-0 no setpoint here gives an inlet inside the envelope
#    (tests/test_physics_v1_invariants.py::test_legacy_envelope_was_unreachable_for_chilled_water_modes).
#  * v1: DERIVED from the envelope, not tuned: supply air = chilled water + CHILLED_WATER_APPROACH_C and is
#    floored at the envelope's lower inlet bound, so setpoints below (inlet_min - approach) add nothing;
#    the top of the range puts the inlet on the envelope's upper bound. The whole inlet band is therefore
#    attainable by a constant policy (see test_full_inlet_band_is_attainable_by_a_constant_policy).
CHILLED_WATER_ACTION_RANGE_C: dict[str, tuple[float, float]] = {
    LEGACY_PHYSICS_VERSION: (5.0, 15.0),
    PHYSICS_V1: (
        SAFETY_ENVELOPE.inlet_min_C - CHILLED_WATER_APPROACH_C,
        SAFETY_ENVELOPE.inlet_max_C - CHILLED_WATER_APPROACH_C,
    ),
}
EPISODE_STEPS = 288  # 24 hours at 5-min intervals

# Observation normalisation ranges.
# inlet_temp widened from the old (15, 30) -- that range was tuned for the
# previous _get_inlet_temp(), which always blended-and-clipped into
# [INLET_MIN, INLET_MAX]=[18,27]. DigitalTwin deliberately applies no such
# clamp (is_safe() must be able to see genuinely unsafe states), and the
# action space's chilled-water setpoint (5-15C) plus the +2C approach means
# achieved inlet can legitimately sit well below 15C, especially right
# after reset/a setpoint change before thermal lag catches up.
OBS_RANGES = {
    "hour": (0, 24),
    "utilisation": (0, 1),
    "outside_temp": (0, 40),
    "inlet_temp": (5, 35),
    "outlet_temp": (18, 50),
    "it_power": (0, 600),
    "wue": (0, 5),
    "pue": (1, 2.5),
    "water_stress": (0, 1),
}


# -----------------------------------------------------------------------------
# Environment v2 schemas (T27). Names and ranges are ORDERED; the hashes below identify them.
# -----------------------------------------------------------------------------
_V1_SETPOINT_RANGE = CHILLED_WATER_ACTION_RANGE_C[PHYSICS_V1]
# The APPLIED setpoint can sit outside the action range: an episode starts at the frozen 10 C reset setpoint and
# the actuator is rate-limited, so applied values span [5 C (legacy floor), top of the action range].
APPLIED_SETPOINT_OBS_RANGE_C = (min(5.0, _V1_SETPOINT_RANGE[0]), _V1_SETPOINT_RANGE[1])
# The nine frozen base features (legacy-0's whole observation). ``water_stress_scenario`` is the synthetic
# scenario variable (OBS_RANGES keeps its historical key "water_stress" for existing consumers).
_BASE_OBS_SCHEMA: tuple[tuple[str, float, float], ...] = (
    ("hour", *OBS_RANGES["hour"]),
    ("utilisation", *OBS_RANGES["utilisation"]),
    ("outside_temp", *OBS_RANGES["outside_temp"]),
    ("inlet_temp", *OBS_RANGES["inlet_temp"]),
    ("outlet_temp", *OBS_RANGES["outlet_temp"]),
    ("it_power", *OBS_RANGES["it_power"]),
    ("wue", *OBS_RANGES["wue"]),
    ("pue", *OBS_RANGES["pue"]),
    ("water_stress_scenario", *OBS_RANGES["water_stress"]),
)
# v2 additions: applied (post rate-limit) chilled-water setpoint, applied mode one-hot, previous EXECUTED action
# (post-shield, normalised), room-thermal state.
_V2_EXTRA_OBS_SCHEMA: tuple[tuple[str, float, float], ...] = (
    ("applied_chilled_water_C", *APPLIED_SETPOINT_OBS_RANGE_C),
    *((f"applied_mode_{m}", 0.0, 1.0) for m in COOLING_MODES),
    ("prev_executed_setpoint_norm", 0.0, 1.0),
    ("prev_executed_mode_norm", 0.0, 1.0),
    ("room_thermal_C", *OBS_RANGES["inlet_temp"]),
)
ACTION_SCHEMA: tuple[tuple[str, float, float], ...] = (
    ("chilled_water_setpoint_norm", 0.0, 1.0),
    ("cooling_mode_norm", 0.0, 1.0),
)


def observation_schema(physics_version: str | None = None) -> tuple[tuple[str, float, float], ...]:
    """Ordered (name, low, high) of the observation. legacy-0: the frozen 9 features; v1: 9 + 8 (env v2)."""
    pv = validate_physics_version(physics_version if physics_version is not None else active_physics_version())
    return _BASE_OBS_SCHEMA if pv == LEGACY_PHYSICS_VERSION else _BASE_OBS_SCHEMA + _V2_EXTRA_OBS_SCHEMA


def _schema_hash(schema: tuple[tuple[str, float, float], ...]) -> str:
    canon = json.dumps([[n, float(lo), float(hi)] for n, lo, hi in schema], separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def observation_schema_hash(physics_version: str | None = None) -> str:
    return _schema_hash(observation_schema(physics_version))


def action_schema_hash() -> str:
    return _schema_hash(ACTION_SCHEMA)


def env_contract(physics_version: str | None = None) -> dict[str, str]:
    """What an artifact must record: versions + schema hashes (+ physics version)."""
    pv = validate_physics_version(physics_version if physics_version is not None else active_physics_version())
    return {
        "env_version": ENV_VERSION,
        "action_semantics_version": ACTION_SEMANTICS_VERSION,
        "reward_version": REWARD_VERSION,
        "shield_version": SHIELD_VERSION,
        "safety_envelope_version": SAFETY_ENVELOPE_VERSION,
        "observation_schema_hash": observation_schema_hash(pv),
        "action_schema_hash": action_schema_hash(),
        "physics_version": pv,
    }


def assert_env_contract(recorded: object, physics_version: str | None = None) -> dict:
    """Reject an artifact whose versions or schema hashes differ from the current environment's.

    A missing ``env_contract`` (every pre-v2 artifact) is rejected. Raises ``EnvContractError``.
    """
    assert_current_env_versions(recorded)
    assert isinstance(recorded, dict)
    pv = recorded.get("physics_version", physics_version)
    want = {"observation_schema_hash": observation_schema_hash(pv), "action_schema_hash": action_schema_hash()}
    bad = {k: recorded.get(k) for k, v in want.items() if recorded.get(k) != v}
    if bad:
        raise EnvContractError(f"artifact schema hash mismatch for {sorted(bad)} (physics_version={pv!r})")
    return dict(recorded)


def _normalise(val: float, lo: float, hi: float) -> float:
    """Normalise into [0,1], clipped -- keeps the declared observation_space
    bounds (Box(0,1)) genuinely honoured even for a rare out-of-range
    physical value, rather than silently leaking values outside it."""
    frac = (val - lo) / (hi - lo) if hi > lo else 0.0
    return float(np.clip(frac, 0.0, 1.0))


def _denormalise(val: float, lo: float, hi: float) -> float:
    return lo + val * (hi - lo)


# =============================================================================
# PATENT: DataCentreEnv — Gymnasium environment implementing the optimisation
# Action space: Box([chilled_water_temp_5_to_15, cooling_mode_0_to_3])
# Observation: 9 base features + (physics v1) applied actuator state, previous executed action, room-thermal state
# Reward: -J = -(α·W_norm + β·(PUE-1)_norm + γ·C_norm) — minimises patent objective
# Safety penalty: -2.0 on any SafetyEnvelope breach (v1) / outlet only (legacy-0)
# =============================================================================


class DataCentreEnv(gym.Env):
    """
    Gymnasium environment for joint water+energy optimisation.

    PATENT: Embodies the composite objective J = α·W + β·E + γ·C as negative
    reward. The agent learns to select chilled water setpoint (5–15°C) and
    cooling mode (0–3) to minimise J while avoiding outlet_temp > 45°C.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        alpha: float = 0.5,
        beta: float = 0.3,
        gamma: float = 0.2,
        water_stress: float = 0.0,
        max_steps: int = EPISODE_STEPS,
        seed: int | None = None,
        pinn: Any = None,
        carbon_intensity_by_hour: np.ndarray | None = None,
        physics_version: str | None = None,
        sim_step_seconds: float | None = None,
        carbon_basis: dict | None = None,
    ) -> None:
        """
        Initialise environment with patent objective weights.

          carbon_basis: label of ``carbon_intensity_by_hour`` (``CarbonSignal.basis()``). A curve loaded here is
                        labelled by the loader; a caller-supplied curve without a label is recorded as
                        ``semantic="unknown", is_fallback=True`` (provenance not established).

          physics_version: twin physics the env runs on (default: the active version). Selects the action
                           range, the safety penalty (v1: whole SafetyEnvelope; legacy-0: outlet only) and
                           the carbon normaliser.
          sim_step_seconds: simulated seconds per env step (default 300 = A-1). v1 only; legacy-0 is fixed
                           at 300 s and refuses any other value.

          water_stress: the synthetic water-stress SCENARIO level (water_stress_scenario). The shield's drought
                           rule is triggered by it; an Aqueduct baseline never reaches this environment.

        PATENT PARAMETERS:
          alpha: Weight for W (WUE) in J = α·W + β·E + γ·C
          beta:  Weight for E (PUE-1) in J
          gamma: Weight for C (cooling power) in J
          pinn:  Optional Physics-Informed NN for surrogate outlet/water/PUE prediction.
        """
        super().__init__()
        self._alpha = alpha
        self._beta = beta
        self._gamma = gamma
        self._water_stress = water_stress
        self._max_steps = max_steps
        self._pinn = pinn
        self._physics_version = validate_physics_version(
            physics_version if physics_version is not None else active_physics_version()
        )
        self._v1 = self._physics_version == PHYSICS_V1
        step_s = DEFAULT_SIM_STEP_SECONDS if sim_step_seconds is None else float(sim_step_seconds)
        if not (np.isfinite(step_s) and step_s > 0):
            raise ValueError(f"sim_step_seconds must be a positive finite number, got {sim_step_seconds!r}")
        if not self._v1 and step_s != DEFAULT_SIM_STEP_SECONDS:
            raise ValueError(f"physics {self._physics_version!r} has a fixed {DEFAULT_SIM_STEP_SECONDS}-s step")
        self._step_s = step_s
        self._dt_h = step_s / 3600.0

        if carbon_intensity_by_hour is None:
            _sig = load_carbon_signal()
            carbon_intensity_by_hour = _sig.curve_by_site_local_hour
            carbon_basis = carbon_basis or _carbon_basis_of(_sig)
        self._carbon_intensity_by_hour = carbon_intensity_by_hour
        self._carbon_basis = (
            dict(carbon_basis) if carbon_basis else _carbon_basis_of(signal_for_curve(carbon_intensity_by_hour))
        )
        # Normalisation ceiling for the carbon reward term: max possible
        # cooling power (150 kW, matching the existing cooling_norm range)
        # at the dirtiest hour in the real curve, over one 5-min interval --
        # a real, data-derived bound rather than a guessed constant.
        # v1: the carbon term is TOTAL facility power (the single carbon definition), so the ceiling is the
        # largest total power the envelope allows (IT max x PUE max) at the dirtiest hour, over one step.
        # legacy-0: cooling-only carbon, ceiling unchanged.
        if self._v1:
            self._carbon_norm_max = (
                MAX_IT_POWER_KW * SAFETY_ENVELOPE.pue_max * float(self._carbon_intensity_by_hour.max()) * self._dt_h
            )
        else:
            self._carbon_norm_max = 150.0 * float(self._carbon_intensity_by_hour.max()) * (INTERVAL_MIN / 60)

        # PATENT: Action = [chilled_water_temp 5–15°C, cooling_mode 0–3]
        # Normalised to [0,1] for continuous control
        self.action_space = gym.spaces.Box(
            low=np.array([0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0], dtype=np.float32),
            dtype=np.float32,
        )

        # Observation: the ordered schema of this physics version (see observation_schema()), all in [0, 1]
        self._obs_schema = observation_schema(self._physics_version)
        n_obs = len(self._obs_schema)
        self.observation_space = gym.spaces.Box(
            low=np.zeros(n_obs, dtype=np.float32),
            high=np.ones(n_obs, dtype=np.float32),
            dtype=np.float32,
        )
        self._prev_executed = np.array([0.0, DROUGHT_OVERRIDE_MODE_INDEX_NORM], dtype=np.float32)
        self._last_info: dict[str, Any] = {}

        self._step_count = 0
        self._state: dict[str, float] = {}
        self._rng = np.random.default_rng(seed)
        self._twin: DigitalTwin | None = None  # created fresh each reset()

    def _compute_utilisation(self, hour: float) -> float:
        """Daily load pattern (workload profile, not physics -- feeds the
        twin's `utilisation` action input, doesn't duplicate anything in
        DigitalTwin)."""
        u = 0.4 + 0.5 * np.sin((hour - 6) * np.pi / 12)
        return float(np.clip(u, 0, 1))

    def _compute_outside_temp(self, hour: float) -> float:
        """Ambient temperature cycle (environment profile, not physics --
        feeds the twin's `outside_temp_C` action input)."""
        return 22 + 5 * np.sin(2 * np.pi * (hour - 14) / 24) + self._rng.normal(0, 1)

    def _step_physics(
        self,
        chilled_water: float,
        mode: str,
    ) -> dict[str, float]:
        """
        Compute one 5-min step by delegating ALL physics to the canonical
        DigitalTwin (src/digital_twin.py) -- this method no longer computes
        IT power, inlet/outlet temperature, COP/cooling power, or water
        consumption itself. Uses the PINN for outlet/water/PUE when
        provided (patent core, optional non-authoritative override) --
        the twin still runs either way, since it also owns actuator state
        (chilled-water rate limiting) and carbon accounting.
        """
        hour = self._twin._time.hour + self._twin._time.minute / 60.0
        util = self._compute_utilisation(hour)
        outside = self._compute_outside_temp(hour)

        action = {
            "utilisation": util,
            "outside_temp_C": outside,
            "cooling_mode": mode,
            "chilled_water_temp_C": chilled_water,
            "water_stress": self._water_stress,
        }
        state = self._twin.step(action, dt_seconds=self._step_s) if self._v1 else self._twin.step(action)

        it_power = state.it_power_kw
        cooling = state.cooling_power_kw
        inlet = state.server_inlet_temp_C

        if self._pinn is not None:
            from src.pinn import encode_cooling_mode

            mode_enc = encode_cooling_mode(mode)
            pred = self._pinn.predict(
                np.array([util], dtype=np.float32),
                np.array([outside], dtype=np.float32),
                np.array([mode_enc], dtype=np.float32),
                np.array([chilled_water], dtype=np.float32),
            )
            outlet = float(pred[0, 0])
            water_consumed = float(pred[0, 1])
            pue = float(pred[0, 2])
            it_energy_kwh = it_power * (self._dt_h if self._v1 else INTERVAL_MIN / 60)
            wue = water_consumed / it_energy_kwh if it_energy_kwh > 0.01 else 0.0
        else:
            outlet = state.server_outlet_temp_C
            # DataCentreState.water_consumed_L is CUMULATIVE; this dict's
            # "water_consumed" is per-step, matching the original contract
            # here -- derive it from the twin's per-step flow, not its
            # running total.
            water_consumed = state.water_flow_lpm * (self._step_s / 60.0 if self._v1 else INTERVAL_MIN)
            pue = state.pue
            wue = state.wue

        intensity = state.carbon_intensity_gco2_per_kwh
        if self._v1:
            # THE carbon definition (same function the API's state/what-if/ESG use), on total power.
            carbon_gco2 = carbon_emissions_gco2(it_power + cooling, intensity, self._dt_h)
        else:
            carbon_gco2 = state.carbon_gco2

        return {
            "hour": hour,
            "utilisation": util,
            "outside_temp": outside,
            "inlet_temp": inlet,
            "outlet_temp": outlet,
            "it_power": it_power,
            "cooling_power": cooling,
            "water_consumed": water_consumed,
            "pue": pue,
            "wue": wue,
            "carbon_intensity_gco2_per_kwh": intensity,
            "carbon_gco2": carbon_gco2,
            "water_stress": self._water_stress,
            "drought_override_active": state.drought_override_active,
        }

    def _applied_actuators(self) -> tuple[float, str, float, str]:
        """(applied chilled-water C, applied mode, room-thermal C, room-thermal source) from the twin.

        Uses the twin's public ``applied_chilled_water_temp_C`` / ``room_thermal_state_C`` if it has them
        (physics v2, T21); otherwise its v1 internals: the rate-limited applied setpoint and the first-order
        lagged inlet state (the only thermal state a v1 twin carries).
        """
        tw = self._twin
        applied_c = getattr(tw, "applied_chilled_water_temp_C", None)
        if applied_c is None:
            applied_c = tw._applied_chilled_water_temp_C
        room = getattr(tw, "room_thermal_state_C", None)
        source = "twin.room_thermal_state_C"
        if room is None:
            room = tw._inlet_temp_C if tw._inlet_temp_C is not None else self._state["inlet_temp"]
            source = "v1_lagged_inlet_state"
        mode = tw._state.cooling_mode
        return float(applied_c), (mode.value if hasattr(mode, "value") else str(mode)), float(room), source

    def _get_obs(self) -> np.ndarray:
        """Observation per ``observation_schema(physics_version)``: 9 base features (+ 8 in env v2 / physics v1)."""
        s = self._state
        r = OBS_RANGES
        base = [
            _normalise(s["hour"], r["hour"][0], r["hour"][1]),
            _normalise(s["utilisation"], r["utilisation"][0], r["utilisation"][1]),
            _normalise(s["outside_temp"], r["outside_temp"][0], r["outside_temp"][1]),
            _normalise(s["inlet_temp"], r["inlet_temp"][0], r["inlet_temp"][1]),
            _normalise(s["outlet_temp"], r["outlet_temp"][0], r["outlet_temp"][1]),
            _normalise(s["it_power"], r["it_power"][0], r["it_power"][1]),
            _normalise(s["wue"], r["wue"][0], r["wue"][1]),
            _normalise(s["pue"], r["pue"][0], r["pue"][1]),
            _normalise(self._water_stress, r["water_stress"][0], r["water_stress"][1]),
        ]
        if not self._v1:
            return np.array(base, dtype=np.float32)
        applied_c, applied_mode, room_c, _src = self._applied_actuators()
        one_hot = [1.0 if m == applied_mode else 0.0 for m in COOLING_MODES]
        extra = [
            _normalise(applied_c, *APPLIED_SETPOINT_OBS_RANGE_C),
            *one_hot,
            float(self._prev_executed[0]),
            float(self._prev_executed[1]),
            _normalise(room_c, *OBS_RANGES["inlet_temp"]),
        ]
        return np.array(base + extra, dtype=np.float32)

    @property
    def water_stress_scenario(self) -> float:
        """The synthetic scenario level that drives the shield's drought rule (never the Aqueduct baseline)."""
        return self._water_stress

    @property
    def observation_names(self) -> tuple[str, ...]:
        return tuple(n for n, _lo, _hi in self._obs_schema)

    @property
    def env_contract(self) -> dict[str, str]:
        return env_contract(self._physics_version)

    def _action_to_control(self, a_x: np.ndarray) -> tuple[float, str]:
        """Decode an EXECUTED action (already shielded) into (chilled-water setpoint C, mode name)."""
        lo, hi = CHILLED_WATER_ACTION_RANGE_C[self._physics_version]
        chilled = _denormalise(float(np.asarray(a_x).flat[0]), lo, hi)
        return chilled, COOLING_MODES[mode_index_of(np.asarray(a_x).flat[1])]

    @staticmethod
    def safety_violations_of(state: dict[str, float], *, legacy: bool = False) -> tuple[str, ...]:
        """Names of the safety limits an env state violates, from THE envelope.

        ``legacy=True`` reproduces legacy-0's outlet-only check (kept so legacy-0 results stay replayable).
        """
        if legacy:
            return () if state["outlet_temp"] <= OUTLET_MAX else ("outlet_above_max",)
        return SAFETY_ENVELOPE.violations(state["inlet_temp"], state["outlet_temp"], state["pue"])

    @property
    def physics_version(self) -> str:
        return self._physics_version

    @property
    def carbon_basis(self) -> dict:
        """Label of the carbon curve this env's reward uses (semantic, is_fallback, aggregation, ...)."""
        return dict(self._carbon_basis)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self._step_count = 0
        hour = float(self._rng.uniform(0, 24))

        # Fresh DigitalTwin per episode, starting at the sampled hour-of-day
        # (only .hour/.minute are read from this synthetic date -- the twin
        # otherwise just needs a real datetime to carry).
        self._twin = DigitalTwin(
            physics_version=self._physics_version,
            max_it_power_kw=MAX_IT_POWER_KW,
            idle_power_fraction=IDLE_FRAC,
            air_flow_m3_s=AIRFLOW_M3_S,
            initial_cooling_mode=CoolingMode.CLOSED_LOOP,
            initial_chilled_water_temp_C=10.0,
            start_time=datetime(2000, 1, 1) + timedelta(hours=hour),
        )
        # Reuse this env's already-loaded carbon curve (same one passed to
        # JointOptimizer/DataCentreEnv at construction) rather than letting
        # the twin independently reload data/cleaned/carbon_intensity.csv --
        # keeps a single carbon source per training run instead of two
        # potentially-different copies of the same file.
        self._twin._carbon_intensity_by_hour = self._carbon_intensity_by_hour

        # NOTE: this first state is ~5 minutes after the sampled `hour`
        # (one twin.step() inside _step_physics), not exactly at it --
        # documented, minor, and avoids a second "peek without stepping"
        # code path just to shave off one interval.
        lo, hi = CHILLED_WATER_ACTION_RANGE_C[self._physics_version]
        self._prev_executed = np.array(
            [_normalise(10.0, lo, hi), DROUGHT_OVERRIDE_MODE_INDEX_NORM], dtype=np.float32
        )  # the reset control (10 C, closed_loop), encoded like any executed action
        self._state = self._step_physics(chilled_water=10.0, mode="closed_loop")
        obs = self._get_obs()
        self._last_info = self._build_info(
            a_e=None, a_x=self._prev_executed.copy(), flags=None, requested=(10.0, "closed_loop")
        )
        return obs.astype(np.float32), dict(self._last_info)

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        # a_e arrives already clipped by SB3; the shield (part of the environment, pure) turns it into the
        # EXECUTED action a_x, which is what the plant is asked to do and what the next observation reports.
        a_x, flags = shield({"water_stress_scenario": self._water_stress}, action)
        chilled, mode = self._action_to_control(a_x)
        self._state = self._step_physics(chilled, mode)
        self._prev_executed = a_x.astype(np.float32)

        # =====================================================================
        # PATENT CORE: Reward = -J = -(α·W + β·E + γ·C)
        # W = WUE (normalised), E = (PUE-1) (normalised), C = cooling power (norm)
        # Minimising J is equivalent to maximising -J
        # =====================================================================
        wue_norm = _normalise(self._state["wue"], 0, 5)
        pue_excess = max(0, self._state["pue"] - 1)
        pue_norm = _normalise(pue_excess, 0, 1.5)
        carbon_norm = _normalise(self._state["carbon_gco2"], 0, self._carbon_norm_max)  # v1: same fn as the API

        J = self._alpha * wue_norm + self._beta * pue_norm + self._gamma * carbon_norm
        reward = -J

        # PATENT: Safety penalty. v1: any breach of THE SafetyEnvelope (inlet, outlet, PUE) costs a flat 2.0;
        # legacy-0: outlet only (frozen).
        if self.safety_violations_of(self._state, legacy=not self._v1):
            reward -= 2.0

        self._step_count += 1
        terminated = self._step_count >= self._max_steps
        truncated = False
        info = self._build_info(a_e=action, a_x=a_x, flags=flags, requested=(chilled, mode))
        self._last_info = info
        return self._get_obs().astype(np.float32), reward, terminated, truncated, dict(info)

    def _build_info(self, *, a_e: Any, a_x: np.ndarray, flags: Any, requested: tuple[float, str]) -> dict[str, Any]:
        """What happened this step: the executed action, whether the shield acted, what the actuator applied."""
        applied_c, applied_mode, room_c, room_src = self._applied_actuators()
        return {
            "state": self._state.copy(),
            "env_version": ENV_VERSION,
            "executed_action": np.asarray(a_x, dtype=np.float32).copy(),
            "env_action": None if a_e is None else np.asarray(a_e, dtype=np.float32).reshape(-1).copy(),
            "shield_active": bool(flags.active) if flags is not None else False,
            "shield_flags": flags.as_dict() if flags is not None else None,
            "requested_setpoint_C": float(requested[0]),
            "requested_mode": requested[1],
            "applied_setpoint_C": applied_c,
            "applied_mode": applied_mode,
            "room_thermal_C": room_c,
            "room_thermal_source": room_src,
        }

    def get_state_dict(self) -> dict[str, float]:
        return self._state.copy()
