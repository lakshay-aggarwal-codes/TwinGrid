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

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .carbon_provider import _a, load_carbon_signal, signal_for_curve
from .carbon_provider import carbon_basis as _carbon_basis_of
from .digital_twin import (
    SAFETY_ENVELOPE,
)
from .logging_config import log_error, log_function_entry, log_function_exit, log_training_progress
from .versions import (
    PHYSICS_V1,
    SAFETY_ENVELOPE_VERSION,
    active_physics_version,
    assert_current_safety_envelope_version,
    validate_physics_version,
)

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
            raise ImportError("stable-baselines3 required. pip install stable-baselines3") from e
    return _sb3


# -----------------------------------------------------------------------------
# T27: the environment and the shield moved to src/rl/env.py and src/rl/safety_filter.py. This module keeps
# every name it used to define (import shim) so existing imports keep working; JointOptimizer stays here.
# -----------------------------------------------------------------------------
from .rl.env import (  # noqa: E402,F401
    ACTION_SCHEMA,
    AIRFLOW_M3_S,
    CHILLED_WATER_ACTION_RANGE_C,
    DEFAULT_SIM_STEP_SECONDS,
    EPISODE_STEPS,
    IDLE_FRAC,
    INTERVAL_MIN,
    MAX_IT_POWER_KW,
    OBS_RANGES,
    OUTLET_MAX,
    DataCentreEnv,
    _denormalise,
    _normalise,
    action_schema_hash,
    assert_env_contract,
    env_contract,
    observation_schema,
    observation_schema_hash,
)
from .rl.safety_filter import (  # noqa: E402,F401
    COOLING_MODES,
    DROUGHT_OVERRIDE_MODE,
    DROUGHT_THRESHOLD,
    ShieldFlags,
    shield,
)

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
        physics_version: str | None = None,
        sim_step_seconds: float | None = None,
        carbon_basis: dict | None = None,
    ) -> None:
        self._alpha = alpha
        self._beta = beta
        self._gamma = gamma
        self._seed = seed
        self._pinn = pinn
        self._physics_version = validate_physics_version(
            physics_version if physics_version is not None else active_physics_version()
        )
        self._sim_step_seconds = sim_step_seconds
        if carbon_intensity_by_hour is None:
            _sig = load_carbon_signal()
            carbon_intensity_by_hour = _sig.curve_by_site_local_hour
            carbon_basis = carbon_basis or _carbon_basis_of(_sig)
        self._carbon_intensity_by_hour = carbon_intensity_by_hour
        self._carbon_basis = (
            dict(carbon_basis) if carbon_basis else _carbon_basis_of(signal_for_curve(carbon_intensity_by_hour))
        )
        self._model = None

    @property
    def carbon_basis(self) -> dict:
        """Label of the carbon curve used for training/evaluation (semantic, is_fallback, aggregation, ...)."""
        return dict(self._carbon_basis)

    def _make_env(self, water_stress: float = 0.0) -> DataCentreEnv:
        return DataCentreEnv(
            alpha=self._alpha,
            beta=self._beta,
            gamma=self._gamma,
            water_stress=water_stress,
            seed=self._seed,
            pinn=self._pinn,
            carbon_intensity_by_hour=self._carbon_intensity_by_hour,
            physics_version=self._physics_version,
            sim_step_seconds=self._sim_step_seconds,
            carbon_basis=self._carbon_basis,
        )

    def _objective_label(self) -> str:
        """Writer label for config.json. Says "real grid carbon" ONLY if the signal is not a fallback."""
        b = self._carbon_basis
        if b.get("is_fallback", True):
            return (
                "J = alpha*W + beta*E + gamma*C (C = carbon term under an ASSUMED intensity "
                f"[semantic={b.get('semantic', 'unknown')}, is_fallback=true]; not measured grid data)"
            )
        return (
            f"J = alpha*W + beta*E + gamma*C (C = carbon term from a {b.get('aggregation')} of "
            f"{_a(str(b.get('semantic')))}-intensity series [is_fallback=false]; modelled, not measured)"
        )

    @staticmethod
    def _count_safety_violations(df: pd.DataFrame, *, legacy: bool = False) -> int:
        """Rows (steps) that breach THE SafetyEnvelope (inlet, outlet, PUE). ``legacy=True`` counts the
        outlet limit only, as legacy-0 always did. NaN counts as a violation (negated comparisons)."""
        outlet_bad = ~(df["outlet_temp"] <= SAFETY_ENVELOPE.outlet_max_C)
        if legacy:
            return int(outlet_bad.sum())
        inlet_bad = ~(df["inlet_temp"] >= SAFETY_ENVELOPE.inlet_min_C) | (
            df["inlet_temp"] > SAFETY_ENVELOPE.inlet_max_C
        )
        pue_bad = ~(df["pue"] <= SAFETY_ENVELOPE.pue_max)
        return int((inlet_bad | outlet_bad | pue_bad).sum())

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
            ppo_kwargs=ppo_kwargs,
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
            rows.append(
                {
                    **state,
                    "chilled_water_temp_C": chilled,
                    "cooling_mode": mode,
                    "reward": reward,
                }
            )
            obs = next_obs
            if term or trunc:
                break

        env.close()
        df = pd.DataFrame(rows)
        logger.info("Episode: %d steps, total_reward=%.2f", len(df), df["reward"].sum())
        return df

    def policy_action(self, obs: np.ndarray, *, deterministic: bool = True) -> np.ndarray:
        """Normalised action [chilled_water, cooling_mode] in [0, 1]^2 for one observation (T8).

        Evaluation hook for src/policy_evaluation.py: the same ``predict`` call ``run_episode``
        makes, exposed so the harness does not reach into ``_model``. Changes no training or
        physics behaviour.
        """
        if self._model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        action, _ = self._model.predict(obs, deterministic=deterministic)
        return np.asarray(action, dtype=np.float32)

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
                "safety_violations": self._count_safety_violations(df, legacy=self._physics_version != PHYSICS_V1),
            }

        normal = run_and_aggregate(normal_stress)
        drought = run_and_aggregate(drought_stress)

        return {
            "carbon_signal": self.carbon_basis,  # T23: what the carbon numbers below are (semantic, is_fallback)
            "normal": normal,
            "drought": drought,
            "comparison": {
                "pue_change_pct": (drought["mean_pue"] - normal["mean_pue"]) / normal["mean_pue"] * 100
                if normal["mean_pue"] > 0
                else 0,
                "wue_change_pct": (drought["mean_wue"] - normal["mean_wue"]) / normal["mean_wue"] * 100
                if normal["mean_wue"] > 0
                else 0,
                "water_reduction_pct": (normal["total_water_consumed_L"] - drought["total_water_consumed_L"])
                / normal["total_water_consumed_L"]
                * 100
                if normal["total_water_consumed_L"] > 0
                else 0,
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
            "patent_objective": self._objective_label(),
            "carbon_signal": self.carbon_basis,
            # T20: what this policy was trained under. A loader rejects an older/missing envelope version.
            "physics_version": self._physics_version,
            "sim_step_seconds": self._sim_step_seconds,
            "safety_envelope_version": SAFETY_ENVELOPE_VERSION,
            # T27: the environment contract this policy was trained under (versions + schema hashes). A loader
            # rejects an artifact whose contract differs or is missing (every pre-v2 artifact).
            "env_contract": env_contract(self._physics_version),
        }
        (path / "config.json").write_text(json.dumps(config, indent=2))
        logger.info("Saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> JointOptimizer:
        """Load PPO model and patent config."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        config = json.loads((path / "config.json").read_text())
        # Gate BEFORE any model code runs: an artifact trained under an older envelope is rejected outright.
        assert_current_safety_envelope_version(config.get("safety_envelope_version"))
        assert_env_contract(config.get("env_contract"), config.get("physics_version"))  # T27: pre-v2 artifacts end here
        sb3 = _get_sb3()
        PPO = sb3["PPO"]
        carbon_curve = config.get("carbon_intensity_by_hour")
        optimizer = cls(
            alpha=config.get("alpha", 0.5),
            beta=config.get("beta", 0.3),
            gamma=config.get("gamma", 0.2),
            seed=config.get("seed"),
            carbon_intensity_by_hour=np.array(carbon_curve) if carbon_curve is not None else None,
            carbon_basis=config.get("carbon_signal"),  # absent in pre-T23 artifacts -> labelled unknown/fallback
            physics_version=config.get("physics_version"),
            sim_step_seconds=config.get("sim_step_seconds"),
        )
        optimizer._model = PPO.load(str(path / "ppo_model"))
        logger.info("Loaded from %s", path)
        return optimizer
