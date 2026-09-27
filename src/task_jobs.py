"""Functions run by an `rq worker` process (see docker-compose.yml's
`worker` service). Each one is plain, synchronous, blocking code -- the
worker process has no event loop to protect, unlike api/services/, where
the same kind of work has to go through asyncio.to_thread instead.

Kept separate from api/services/optimization_service.py because the RQ
worker process imports this module directly and must not need FastAPI,
the DB session machinery, or anything else API-request-specific.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def train_optimizer_job(alpha: float, beta: float, gamma: float, water_stress: float) -> dict[str, Any]:
    """Same fallback training _train_fallback_optimizer() in
    optimization_service.py does, but as a queued job instead of inline in
    a request. Saves to OPTIMIZER_MODEL_PATH (same path the live API's
    _load_saved_optimizer() reads from) so once this job finishes, the NEXT
    /api/optimize call picks up the freshly-trained model instead of
    retraining again -- the queued job and the live singleton share the
    same artifact path, not separate state.
    """
    import os

    from src.optimizer import JointOptimizer

    fallback_timesteps = int(os.getenv("FALLBACK_TRAIN_TIMESTEPS", "5000"))
    optimizer_path = Path(os.getenv("OPTIMIZER_MODEL_PATH", "models/optimizer"))

    optimizer = JointOptimizer(alpha=alpha, beta=beta, gamma=gamma)
    optimizer.train(total_timesteps=fallback_timesteps, n_envs=1, water_stress=water_stress)
    optimizer_path.mkdir(parents=True, exist_ok=True)
    optimizer.save(optimizer_path)

    return {
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "water_stress": water_stress,
        "total_timesteps": fallback_timesteps,
        "saved_to": str(optimizer_path),
    }
