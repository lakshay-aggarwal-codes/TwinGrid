"""Optimizer singleton + business logic for POST /api/optimize.

Nothing in here may block the event loop: model admission and the per-step ``predict()`` rollout
are synchronous, CPU-bound work, so each one runs in a worker thread (``asyncio.to_thread``).
Otherwise a single ``/api/optimize`` call would freeze every other request -- including
``/healthz``, which would make an orchestrator's health check restart the container mid-request.

T19: this module no longer loads a PPO file and no longer trains anything in a request. The API
process is locked to the ``api`` artifact profile, whose format allow-list is json / npz / keras;
an SB3 ``.zip`` (a pickle container) is not loadable here, and the shipped PPO artifact is
``quarantined`` in the registry anyway. So ``/api/optimize`` answers ``503 model_unavailable``
until a policy exists in a safe format AND is ``promoted``. That is the expected, documented
state -- not a bug. The 503 is rate-limited internally (one gate evaluation per
``MODEL_RETRY_INTERVAL_S``) so a client hammering the endpoint cannot flood the logs or the
``model_load_failures_total`` counter.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import HTTPException, status

from api.middleware.metrics import MODEL_INFERENCE_COUNT, registry
from src.artifacts import loaders
from src.optimizer import DataCentreEnv, JointOptimizer

logger = logging.getLogger(__name__)

# The API process may never load a pickle container. Lock the artifact profile for the life of the
# process (ARTIFACT_PROFILE can no longer change it) and publish the artifact metrics.
loaders.lock_profile("api")
loaders.bind_prometheus(registry)

MODEL_UNAVAILABLE_DETAIL = "model_unavailable"
MODEL_RETRY_INTERVAL_S = 30.0

OPTIMIZER_MODEL_PATH = Path(os.getenv("OPTIMIZER_MODEL_PATH", "models/optimizer"))

STEPS_PER_HOUR = 12

_optimizer: Optional[JointOptimizer] = None
_train_lock = asyncio.Lock()  # name kept for compatibility: serialises the one-time admission check
_last_unavailable_at: Optional[float] = None


def get_optimizer() -> Optional[JointOptimizer]:
    """The loaded/trained optimizer, or None if none is ready yet."""
    return _optimizer


def _load_saved_optimizer() -> Optional[JointOptimizer]:
    """BLOCKING. Admit the saved optimizer, or return None.

    The PPO artifact is run through the ArtifactGate (status, integrity, compatibility, format).
    In the ``api`` profile an SB3 ``.zip`` is refused at the format check even if every other
    check passes, so no PPO file is ever opened by this process; the failure is counted in
    ``model_load_failures_total{reason}`` by the gate. Returns None (never raises) so startup
    continues and the feature reports itself unavailable.
    """
    config, weights = OPTIMIZER_MODEL_PATH / "config.json", OPTIMIZER_MODEL_PATH / "ppo_model.zip"
    if not weights.exists():
        logger.info("No saved optimizer at %s", OPTIMIZER_MODEL_PATH)
        return None
    try:
        loaders.authorize([config, weights], artifact="ppo_optimizer")
    except loaders.ModelUnavailableError as exc:
        logger.warning("Optimizer unavailable: %s", exc.reason)
        return None
    except Exception:
        logger.warning("Optimizer admission check failed", exc_info=True)
        return None
    # Reached only if a future task registers a promoted policy in an API-loadable format AND adds
    # the loader for it. Until then the API has no way to construct a JointOptimizer from disk.
    logger.error("Optimizer artifact passed the gate but this service has no safe loader for it; ignoring it")
    loaders.record_load_failure("ppo_optimizer", "load_error")
    return None


def _raise_model_unavailable() -> None:
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=MODEL_UNAVAILABLE_DETAIL)


async def warm_up() -> None:
    """Best-effort admission check at startup. Never trains, never raises."""
    global _optimizer, _last_unavailable_at
    try:
        async with _train_lock:
            if _optimizer is None:
                _optimizer = await asyncio.to_thread(_load_saved_optimizer)
                if _optimizer is None:
                    _last_unavailable_at = time.monotonic()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Optimizer warm-up failed -- /api/optimize will report model_unavailable")


async def _ensure_optimizer(alpha: float, beta: float, gamma: float, water_stress: float) -> JointOptimizer:
    """The admitted optimizer, else HTTP 503 ``model_unavailable``. Never trains in a request.

    ``alpha``/``beta``/``gamma``/``water_stress`` are unused now (they fed the removed fallback
    training) and kept so existing callers keep working.
    """
    global _optimizer, _last_unavailable_at
    if _optimizer is not None:
        return _optimizer
    async with _train_lock:
        if _optimizer is not None:
            return _optimizer
        now = time.monotonic()
        if _last_unavailable_at is not None and now - _last_unavailable_at < MODEL_RETRY_INTERVAL_S:
            _raise_model_unavailable()
        _optimizer = await asyncio.to_thread(_load_saved_optimizer)
        if _optimizer is None:
            _last_unavailable_at = time.monotonic()
            _raise_model_unavailable()
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

    Raises HTTP 503 ``model_unavailable`` when no admitted optimizer exists (see module docstring).

    Concurrency note: the rollout always uses a FRESH DataCentreEnv built from
    this call's own alpha/beta/gamma -- so per-request results are correctly
    isolated even under concurrent requests. The only shared mutable state is
    whether the optimizer has been admitted yet; ``_train_lock`` makes sure
    only one concurrent request ever evaluates that.
    Results still need api.serialization.to_jsonable before being stored or
    returned.
    """
    optimizer = await _ensure_optimizer(alpha, beta, gamma, water_stress)
    MODEL_INFERENCE_COUNT.labels(model="ppo_optimizer").inc()
    return await asyncio.to_thread(_rollout, optimizer, alpha, beta, gamma, water_stress, hours)
