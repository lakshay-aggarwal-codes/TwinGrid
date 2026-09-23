"""Optimizer singleton + business logic for POST /api/optimize."""

from __future__ import annotations

import asyncio
from typing import Any
from api.middleware.metrics import MODEL_INFERENCE_COUNT
import pandas as pd

from src.optimizer import DataCentreEnv, JointOptimizer

_optimizer: JointOptimizer | None = None
_train_lock = asyncio.Lock()


def get_optimizer() -> JointOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = JointOptimizer()
    return _optimizer


async def run_optimization(
    alpha: float, beta: float, gamma: float, water_stress: float, hours: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Run RL optimization, returning (raw_results_with_datetime, summary).

    Concurrency note: the rollout below always uses a FRESH DataCentreEnv
    built from this call's own alpha/beta/gamma -- so per-request results
    are correctly isolated even under concurrent requests. The only shared
    mutable state is whether optimizer._model has been trained yet at all;
    _train_lock ensures only one concurrent request ever triggers that
    one-time training, instead of N concurrent first-requests each kicking
    off their own training run against the same model object.
    """
    optimizer = get_optimizer()
    async with _train_lock:
        if optimizer._model is None:
            optimizer._alpha = alpha
            optimizer._beta = beta
            optimizer._gamma = gamma
            optimizer.train(total_timesteps=5000, n_envs=2, water_stress=water_stress)

    steps_per_hour = 12
    n_steps = hours * steps_per_hour
    env = DataCentreEnv(alpha=alpha, beta=beta, gamma=gamma, water_stress=water_stress, max_steps=n_steps)
    obs, _ = env.reset()
    MODEL_INFERENCE_COUNT.labels(model="ppo_optimizer").inc()
    rows = []
    for _ in range(n_steps):
        action, _ = optimizer._model.predict(obs, deterministic=True)
        next_obs, reward, term, trunc, info = env.step(action)
        state = info["state"]
        chilled, mode = env._action_to_control(action)
        rows.append({**state, "chilled_water_temp_C": chilled, "cooling_mode": mode, "reward": reward})
        obs = next_obs
        if term or trunc:
            break
    env.close()

    df = pd.DataFrame(rows)
    results = df.to_dict("records")
    summary = {
        "mean_pue": float(df["pue"].mean()),
        "mean_wue": float(df["wue"].mean()),
        "mean_cooling_power_kw": float(df["cooling_power"].mean()),
        "total_water_consumed_L": float(df["water_consumed"].sum()),
        "total_reward": float(df["reward"].sum()),
        "safety_violations": int((df["outlet_temp"] > 45).sum()),
    }
    return results, summary