"""
Joint Water and Energy Optimisation for Data Centre Cooling Systems.

PATENT CLAIM: Method and system for joint minimisation of a composite objective
J = α·W + β·E + γ·C, where:
  - W = Water Usage Effectiveness (WUE) — normalised water consumption per IT energy
  - E = Energy overhead (PUE - 1) — excess facility power beyond IT load
  - C = Cooling power consumption — auxiliary cooling system energy

The invention optimises chilled water setpoint and cooling mode selection via
reinforcement learning to simultaneously reduce water footprint, energy waste,
and cooling load while maintaining thermal safety constraints.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from .carbon_provider import load_diurnal_carbon_intensity
from .digital_twin import DigitalTwin, CoolingMode, OUTLET_TEMP_MAX
import json
import logging
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd

from .logging_config import log_function_entry, log_function_exit, log_error, log_training_progress

logger = logging.getLogger(__name__)

# Lazy import for stable-baselines3
_sb3 = None


def _get_sb3():
    global _sb3
    if _sb3 is None:
        try:
            from stable_baselines3 import PPO
            from stable_baselines3.common.vec_env import DummyVecEnv
            _sb3 = {"PPO": PPO, "DummyVecEnv": DummyVecEnv}
        except ImportError as e:
            raise ImportError(
                "stable-baselines3 required. pip install stable-baselines3"
            ) from e
    return _sb3


# -----------------------------------------------------------------------------
# PATENT: Cooling mode enumeration — maps discrete control to physical systems
# 0=free_air, 1=closed_loop, 2=evaporative, 3=hybrid
# -----------------------------------------------------------------------------
COOLING_MODES = ["free_air", "closed_loop", "evaporative", "hybrid"]

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
EPISODE_STEPS = 288  # 24 hours at 5-min intervals
DROUGHT_THRESHOLD = 0.7
DROUGHT_OVERRIDE_MODE = "closed_loop" 

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
# Observation: 8 normalised state variables
# Reward: -J = -(α·W_norm + β·(PUE-1)_norm + γ·C_norm) — minimises patent objective
# Safety penalty: -2.0 if outlet_temp > 45°C (thermal constraint violation)
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
    ) -> None:
        """
        Initialise environment with patent objective weights.

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

        if carbon_intensity_by_hour is None:
            carbon_intensity_by_hour, _ = load_diurnal_carbon_intensity()
        self._carbon_intensity_by_hour = carbon_intensity_by_hour
        # Normalisation ceiling for the carbon reward term: max possible
        # cooling power (150 kW, matching the existing cooling_norm range)
        # at the dirtiest hour in the real curve, over one 5-min interval --
        # a real, data-derived bound rather than a guessed constant.
        self._carbon_norm_max = 150.0 * float(self._carbon_intensity_by_hour.max()) * (INTERVAL_MIN / 60)

        # PATENT: Action = [chilled_water_temp 5–15°C, cooling_mode 0–3]
        # Normalised to [0,1] for continuous control
        self.action_space = gym.spaces.Box(
            low=np.array([0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0], dtype=np.float32),
            dtype=np.float32,
        )

        # PATENT: 8 normalised state variables for observation
        self.observation_space = gym.spaces.Box(
            low=np.zeros(9, dtype=np.float32),
            high=np.ones(9, dtype=np.float32),
            dtype=np.float32,
        )

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
        state = self._twin.step(action)

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
            it_energy_kwh = it_power * (INTERVAL_MIN / 60)
            wue = water_consumed / it_energy_kwh if it_energy_kwh > 0.01 else 0.0
        else:
            outlet = state.server_outlet_temp_C
            # DataCentreState.water_consumed_L is CUMULATIVE; this dict's
            # "water_consumed" is per-step, matching the original contract
            # here -- derive it from the twin's per-step flow, not its
            # running total.
            water_consumed = state.water_flow_lpm * INTERVAL_MIN
            pue = state.pue
            wue = state.wue

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
            "carbon_intensity_gco2_per_kwh": state.carbon_intensity_gco2_per_kwh,
            "carbon_gco2": state.carbon_gco2,
            "water_stress": self._water_stress,
            "drought_override_active": state.drought_override_active,
        }

    def _get_obs(self) -> np.ndarray:
        """9 normalised state variables."""
        s = self._state
        r = OBS_RANGES
        return np.array([
            _normalise(s["hour"], r["hour"][0], r["hour"][1]),
            _normalise(s["utilisation"], r["utilisation"][0], r["utilisation"][1]),
            _normalise(s["outside_temp"], r["outside_temp"][0], r["outside_temp"][1]),
            _normalise(s["inlet_temp"], r["inlet_temp"][0], r["inlet_temp"][1]),
            _normalise(s["outlet_temp"], r["outlet_temp"][0], r["outlet_temp"][1]),
            _normalise(s["it_power"], r["it_power"][0], r["it_power"][1]),
            _normalise(s["wue"], r["wue"][0], r["wue"][1]),
            _normalise(s["pue"], r["pue"][0], r["pue"][1]),
            _normalise(self._water_stress, r["water_stress"][0], r["water_stress"][1]),
        ], dtype=np.float32)

    def _action_to_control(self, action: np.ndarray) -> tuple[float, str]:
        chilled = _denormalise(float(np.asarray(action).flat[0]), 5.0, 15.0)
        mode_idx = int(np.clip(round(np.asarray(action).flat[1] * 3), 0, 3))
        mode = COOLING_MODES[mode_idx]

        if self._water_stress > DROUGHT_THRESHOLD:
            mode = DROUGHT_OVERRIDE_MODE

        return chilled, mode

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
        self._state = self._step_physics(chilled_water=10.0, mode="closed_loop")
        obs = self._get_obs()
        return obs.astype(np.float32), {}

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        chilled, mode = self._action_to_control(action)
        self._state = self._step_physics(chilled, mode)

        # =====================================================================
        # PATENT CORE: Reward = -J = -(α·W + β·E + γ·C)
        # W = WUE (normalised), E = (PUE-1) (normalised), C = cooling power (norm)
        # Minimising J is equivalent to maximising -J
        # =====================================================================
        wue_norm = _normalise(self._state["wue"], 0, 5)
        pue_excess = max(0, self._state["pue"] - 1)
        pue_norm = _normalise(pue_excess, 0, 1.5)
        carbon_norm = _normalise(self._state["carbon_gco2"], 0, self._carbon_norm_max)

        J = self._alpha * wue_norm + self._beta * pue_norm + self._gamma * carbon_norm
        reward = -J

        # PATENT: Safety penalty — thermal constraint violation
        if self._state["outlet_temp"] > OUTLET_MAX:
            reward -= 2.0

        self._step_count += 1
        terminated = self._step_count >= self._max_steps
        truncated = False
        info = {"state": self._state.copy()}
        return self._get_obs().astype(np.float32), reward, terminated, truncated, info

    def get_state_dict(self) -> dict[str, float]:
        return self._state.copy()


# =============================================================================
# PATENT: JointOptimizer — PPO-based controller minimising J = α·W + β·E + γ·C
# Tunable weights enable trade-off between water conservation, energy efficiency,
# and cooling load. Supports scenario comparison (normal vs drought).
# =============================================================================


class JointOptimizer:
    """
    Joint water+energy RL optimizer using PPO.

    PATENT: Implements the invention's composite objective J = α·W + β·E + γ·C
    with tunable conservation weights. Trains a policy to select chilled water
    setpoint and cooling mode that minimises J over 24-hour episodes.
    """

    def __init__(
        self,
        *,
        alpha: float = 0.5,
        beta: float = 0.3,
        gamma: float = 0.2,
        seed: int | None = None,
        pinn: Any = None,
        carbon_intensity_by_hour: np.ndarray | None = None,
    ) -> None:  
        self._alpha = alpha
        self._beta = beta
        self._gamma = gamma
        self._seed = seed
        self._pinn = pinn
        if carbon_intensity_by_hour is None:
            carbon_intensity_by_hour, _ = load_diurnal_carbon_intensity()
        self._carbon_intensity_by_hour = carbon_intensity_by_hour
        self._model = None

    def _make_env(self, water_stress: float = 0.0) -> DataCentreEnv:
        return DataCentreEnv(
            alpha=self._alpha,
            beta=self._beta,
            gamma=self._gamma,
            water_stress=water_stress,
            seed=self._seed,
            pinn=self._pinn,
            carbon_intensity_by_hour=self._carbon_intensity_by_hour,
        )

    def train(
        self,
        total_timesteps: int = 50_000,
        *,
        n_envs: int = 4,
        water_stress: float = 0.0,
        **ppo_kwargs: Any,
    ) -> None:
        """
        Train PPO agent to minimise J = α·W + β·E + γ·C.

        PATENT: The learned policy optimises chilled water temp and cooling
        mode selection to reduce water footprint (W), energy overhead (E),
        and cooling load (C) jointly.
        """
        log_function_entry(
            "JointOptimizer.train",
            total_timesteps=total_timesteps,
            n_envs=n_envs,
            water_stress=water_stress,
            ppo_kwargs=ppo_kwargs
        )
        
        try:
            sb3 = _get_sb3()
            DummyVecEnv = sb3["DummyVecEnv"]
            PPO = sb3["PPO"]

            def env_fn():
                return self._make_env(water_stress)

            env = DummyVecEnv([env_fn] * n_envs)
            default_kwargs = {
                "policy": "MlpPolicy",
                "learning_rate": 3e-4,
                "n_steps": 2048,
                "batch_size": 64,
                "n_epochs": 10,
                "gamma": 0.99,
                "verbose": 1,
            }
            default_kwargs.update(ppo_kwargs)
            self._model = PPO(env=env, **default_kwargs)
            
            # Log training progress
            log_training_progress("JointOptimizer", epoch=0, loss=0, accuracy=total_timesteps)
            
            self._model.learn(total_timesteps=total_timesteps)
            env.close()
            logger.info("Training complete: %d timesteps", total_timesteps)
            
            log_function_exit("JointOptimizer.train", result=f"Training completed with {total_timesteps} timesteps")
        except Exception as e:
            log_error("JointOptimizer.train", e)
            raise

    def run_episode(
        self,
        water_stress: float = 0.0,
        *,
        deterministic: bool = True,
    ) -> pd.DataFrame:
        """
        Run one 24-hour episode and return results DataFrame.

        PATENT: Each step applies the learned policy to minimise J.
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")

        env = self._make_env(water_stress)
        obs, _ = env.reset()
        rows = []

        for _ in range(EPISODE_STEPS):
            action, _ = self._model.predict(obs, deterministic=deterministic)
            next_obs, reward, term, trunc, info = env.step(action)
            state = info["state"]
            chilled, mode = env._action_to_control(action)
            rows.append({
                **state,
                "chilled_water_temp_C": chilled,
                "cooling_mode": mode,
                "reward": reward,
            })
            obs = next_obs
            if term or trunc:
                break

        env.close()
        df = pd.DataFrame(rows)
        logger.info("Episode: %d steps, total_reward=%.2f", len(df), df["reward"].sum())
        return df

    def compare_scenarios(
        self,
        normal_stress: float = 0.0,
        drought_stress: float = 0.8,
    ) -> dict[str, Any]:
        """
        Compare normal vs drought water stress scenarios.

        PATENT: Demonstrates policy adaptation under different water availability
        constraints. Drought scenario tests water conservation under stress.
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")

        def run_and_aggregate(stress: float) -> dict[str, float]:
            df = self.run_episode(water_stress=stress)
            return {
                "mean_pue": float(df["pue"].mean()),
                "mean_wue": float(df["wue"].mean()),
                "mean_cooling_power_kw": float(df["cooling_power"].mean()),
                "mean_outlet_temp_C": float(df["outlet_temp"].mean()),
                "total_water_consumed_L": float(df["water_consumed"].sum()),
                "mean_carbon_intensity_gco2_per_kwh": float(df["carbon_intensity_gco2_per_kwh"].mean()),
                "total_carbon_gco2": float(df["carbon_gco2"].sum()),
                "drought_override_active_pct": float(df["drought_override_active"].mean() * 100),
                "total_reward": float(df["reward"].sum()),
                "safety_violations": int((df["outlet_temp"] > OUTLET_MAX).sum()),
            }
        normal = run_and_aggregate(normal_stress)
        drought = run_and_aggregate(drought_stress)

        return {
            "normal": normal,
            "drought": drought,
            "comparison": {
                "pue_change_pct": (drought["mean_pue"] - normal["mean_pue"]) / normal["mean_pue"] * 100 if normal["mean_pue"] > 0 else 0,
                "wue_change_pct": (drought["mean_wue"] - normal["mean_wue"]) / normal["mean_wue"] * 100 if normal["mean_wue"] > 0 else 0,
                "water_reduction_pct": (normal["total_water_consumed_L"] - drought["total_water_consumed_L"]) / normal["total_water_consumed_L"] * 100 if normal["total_water_consumed_L"] > 0 else 0,
            },
        }

    def save(self, path: str | Path) -> None:
        """Save PPO model and patent config (alpha, beta, gamma, carbon curve)."""
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self._model.save(str(path / "ppo_model"))
        config = {
            "alpha": self._alpha,
            "beta": self._beta,
            "gamma": self._gamma,
            "seed": self._seed,
            "carbon_intensity_by_hour": self._carbon_intensity_by_hour.tolist(),
            "patent_objective": "J = alpha*W + beta*E + gamma*C (C = real grid carbon emissions)",
        }
        (path / "config.json").write_text(json.dumps(config, indent=2))
        logger.info("Saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> JointOptimizer:
        """Load PPO model and patent config."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        sb3 = _get_sb3()
        PPO = sb3["PPO"]
        config = json.loads((path / "config.json").read_text())
        carbon_curve = config.get("carbon_intensity_by_hour")
        optimizer = cls(
            alpha=config.get("alpha", 0.5),
            beta=config.get("beta", 0.3),
            gamma=config.get("gamma", 0.2),
            seed=config.get("seed"),
            carbon_intensity_by_hour=np.array(carbon_curve) if carbon_curve is not None else None,
        )
        optimizer._model = PPO.load(str(path / "ppo_model"))
        logger.info("Loaded from %s", path)
        return optimizer