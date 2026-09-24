"""Optimizer singleton + business logic for POST /api/optimize.

Nothing in here may block the event loop: PPO loading, PPO training and the
per-step ``predict()`` rollout are all synchronous, CPU-bound work, so each one
runs in a worker thread (``asyncio.to_thread``). Otherwise a single
``/api/optimize`` call would freeze every other request -- including
``/healthz``, which would make an orchestrator's health check restart the
container mid-request.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from api.middleware.metrics import MODEL_INFERENCE_COUNT
from src.optimizer import DataCentreEnv, JointOptimizer

logger = logging.getLogger(__name__)

OPTIMIZER_MODEL_PATH = Path(os.getenv("OPTIMIZER_MODEL_PATH", "models/optimizer"))

STEPS_PER_HOUR = 12
# Only used if no compatible saved model exists. Deliberately small: this runs
# inside a request. Real training (50k steps) is `python notebooks/train_all.py`.
FALLBACK_TRAIN_TIMESTEPS = 5000

_optimizer: Optional[JointOptimizer] = None
_train_lock = asyncio.Lock()


def get_optimizer() -> Optional[JointOptimizer]:
    """The loaded/trained optimizer, or None if none is ready yet."""
    return _optimizer


def _load_saved_optimizer() -> Optional[JointOptimizer]:
    """BLOCKING. Load OPTIMIZER_MODEL_PATH; return None if it is missing,
    unloadable, or was trained for a different observation/action space.

    The shape check matters: PPO.load() succeeds for any well-formed zip, and
    a policy trained against an older env (e.g. 8-dim observations, while
    DataCentreEnv now emits 9) only fails later, inside predict(), on the
    first request. Treating it as "not loadable" makes us retrain instead.
    """
    if not (OPTIMIZER_MODEL_PATH / "ppo_model.zip").exists():
        logger.info("No saved optimizer at %s", OPTIMIZER_MODEL_PATH)
        return None
    try:
        loaded = JointOptimizer.load(OPTIMIZER_MODEL_PATH)
    except Exception:
        logger.warning("Could not load saved optimizer from %s", OPTIMIZER_MODEL_PATH, exc_info=True)
        return None

    env = DataCentreEnv()
    try:
        expected_obs, expected_act = env.observation_space.shape, env.action_space.shape
    finally:
        env.close()
    model = loaded._model
    if model.observation_space.shape != expected_obs or model.action_space.shape != expected_act:
        logger.warning(
            "Saved optimizer at %s is incompatible with the current DataCentreEnv "
            "(model obs/action %s/%s, env %s/%s) -- ignoring it. Re-run "
            "`python notebooks/train_all.py` to regenerate models/optimizer.",
            OPTIMIZER_MODEL_PATH,
            model.observation_space.shape,
            model.action_space.shape,
            expected_obs,
            expected_act,
        )
        return None
    logger.info("Loaded optimizer from %s", OPTIMIZER_MODEL_PATH)
    return loaded


def _train_fallback_optimizer(alpha: float, beta: float, gamma: float, water_stress: float) -> JointOptimizer:
    """BLOCKING. Quick in-memory PPO training, used only when no compatible
    saved model exists.

    Not persisted on purpose: a 5k-step model must never overwrite (or be
    mistaken for) the properly trained artifact in models/optimizer.
    """
    logger.warning("Training a fallback optimizer (%d timesteps) in a worker thread", FALLBACK_TRAIN_TIMESTEPS)
    optimizer = JointOptimizer(alpha=alpha, beta=beta, gamma=gamma)
    optimizer.train(total_timesteps=FALLBACK_TRAIN_TIMESTEPS, n_envs=2, water_stress=water_stress)
    return optimizer


async def warm_up() -> None:
    """Best-effort load of the saved model at startup so the first
    /api/optimize call doesn't pay for importing torch + loading weights.
    Never trains, and never raises."""
    global _optimizer
    try:
        async with _train_lock:
            if _optimizer is None:
                _optimizer = await asyncio.to_thread(_load_saved_optimizer)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Optimizer warm-up failed -- it will be loaded/trained on first use")


async def _ensure_optimizer(alpha: float, beta: float, gamma: float, water_stress: float) -> JointOptimizer:
    """Load the saved model, else train a fallback -- once, under the lock, in a thread."""
    global _optimizer
    if _optimizer is not None:
        return _optimizer
    async with _train_lock:
        if _optimizer is None:
            loaded = await asyncio.to_thread(_load_saved_optimizer)
            if loaded is None:
                loaded = await asyncio.to_thread(_train_fallback_optimizer, alpha, beta, gamma, water_stress)
            _optimizer = loaded
        return _optimizer


def _rollout(
    optimizer: JointOptimizer, alpha: float, beta: float, gamma: float, water_stress: float, hours: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """BLOCKING. Roll the policy out on a FRESH DataCentreEnv built from this
    call's own alpha/beta/gamma, so concurrent requests stay isolated."""
    n_steps = hours * STEPS_PER_HOUR
    env = DataCentreEnv(alpha=alpha, beta=beta, gamma=gamma, water_stress=water_stress, max_steps=n_steps)
    rows: list[dict[str, Any]] = []
    try:
        obs, _ = env.reset()
        for _ in range(n_steps):
            action, _ = optimizer._model.predict(obs, deterministic=True)
            next_obs, reward, term, trunc, info = env.step(action)
            state = info["state"]
            chilled, mode = env._action_to_control(action)
            rows.append({**state, "chilled_water_temp_C": chilled, "cooling_mode": mode, "reward": reward})
            obs = next_obs
            if term or trunc:
                break
    finally:
        env.close()

    df = pd.DataFrame(rows)
    summary = {
        "mean_pue": float(df["pue"].mean()),
        "mean_wue": float(df["wue"].mean()),
        "mean_cooling_power_kw": float(df["cooling_power"].mean()),
        "total_water_consumed_L": float(df["water_consumed"].sum()),
        "total_reward": float(df["reward"].sum()),
        "safety_violations": int((df["outlet_temp"] > 45).sum()),
    }
    return df.to_dict("records"), summary


async def run_optimization(
    alpha: float, beta: float, gamma: float, water_stress: float, hours: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Run RL optimization, returning (raw_results, summary).

    Concurrency note: the rollout always uses a FRESH DataCentreEnv built from
    this call's own alpha/beta/gamma -- so per-request results are correctly
    isolated even under concurrent requests. The only shared mutable state is
    whether the optimizer's model has been loaded/trained yet; ``_train_lock``
    makes sure only one concurrent request ever does that one-time work.
    Results still need api.serialization.to_jsonable before being stored or
    returned.
    """
    optimizer = await _ensure_optimizer(alpha, beta, gamma, water_stress)
    MODEL_INFERENCE_COUNT.labels(model="ppo_optimizer").inc()
    return await asyncio.to_thread(_rollout, optimizer, alpha, beta, gamma, water_stress, hours)
