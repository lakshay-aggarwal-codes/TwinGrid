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
    """Train a *candidate* optimizer as a queued job.

    The short fallback run (FALLBACK_TRAIN_TIMESTEPS, default 5000 steps) is far
    weaker than the full-length production model, so it must NEVER be saved to
    the live path (OPTIMIZER_MODEL_PATH, default models/optimizer) -- doing so
    would silently replace a well-trained model with a weak one on the next
    restart. It is saved to its own directory under OPTIMIZER_CANDIDATE_DIR
    (default models/optimizer_candidates/<timestamp>_<id>) and only promoted to
    the live path by a deliberate, evaluated step (roadmap Stage 3).
    """
    import os
    import uuid
    from datetime import datetime, timezone

    from src.optimizer import JointOptimizer

    fallback_timesteps = int(os.getenv("FALLBACK_TRAIN_TIMESTEPS", "5000"))
    candidates_root = Path(os.getenv("OPTIMIZER_CANDIDATE_DIR", "models/optimizer_candidates"))
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}"
    candidate_path = candidates_root / run_id

    optimizer = JointOptimizer(alpha=alpha, beta=beta, gamma=gamma)
    optimizer.train(total_timesteps=fallback_timesteps, n_envs=1, water_stress=water_stress)
    candidate_path.mkdir(parents=True, exist_ok=True)
    optimizer.save(candidate_path)

    return {
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "water_stress": water_stress,
        "total_timesteps": fallback_timesteps,
        "saved_to": str(candidate_path),
        "promoted": False,
    }
