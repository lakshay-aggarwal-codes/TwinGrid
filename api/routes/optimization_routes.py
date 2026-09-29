from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_operator
from api.rate_limit import limiter
from api.repositories import data_repository
from api.schemas.optimization import OptimizeRequest
from api.serialization import to_jsonable
from api.services import audit_service, optimization_service
from database import get_db
from models.db_models import User
from src.task_queue import JobNotFoundError, enqueue, get_status

router = APIRouter(tags=["optimization"])


@router.post("/api/optimize")
@limiter.limit("10/minute")
async def optimize(
    request: Request,
    body: OptimizeRequest,
    _user: Annotated[User, Depends(require_operator)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run RL optimization. Minimizes J = alpha*W + beta*E + gamma*C. Requires 'operator' role. Rate limited: 10/minute."""
    results, summary = await optimization_service.run_optimization(
        body.alpha, body.beta, body.gamma, body.water_stress, body.hours
    )
    serialized_results = to_jsonable(results)
    summary = to_jsonable(summary)
    opt_result = await data_repository.save_optimization_result(
        session,
        alpha=body.alpha,
        beta=body.beta,
        gamma=body.gamma,
        water_stress=body.water_stress,
        hours=body.hours,
        mean_pue=summary["mean_pue"],
        mean_wue=summary["mean_wue"],
        mean_cooling_power_kw=summary["mean_cooling_power_kw"],
        total_water_consumed_L=summary["total_water_consumed_L"],
        total_reward=summary["total_reward"],
        safety_violations=summary["safety_violations"],
        results_json=serialized_results,
    )
    # Adjusting live cooling-optimization parameters is exactly the kind of
    # operator action worth a durable, who/when/what-params record.
    await audit_service.log_action(
        session,
        action="optimize_triggered",
        user=_user,
        resource_type="optimization_result",
        resource_id=opt_result.id,
        details={
            "alpha": body.alpha,
            "beta": body.beta,
            "gamma": body.gamma,
            "water_stress": body.water_stress,
            "hours": body.hours,
        },
        request=request,
    )
    return {"results": serialized_results, "summary": summary}


@router.post("/api/optimize/train_async")
@limiter.limit("5/minute")
async def train_optimizer_async(
    request: Request,
    body: OptimizeRequest,
    _user: Annotated[User, Depends(require_operator)],
) -> dict[str, str]:
    """Enqueue PPO (re)training as an RQ job instead of running it inline
    (see src/task_queue.py, src/task_jobs.py). Returns immediately with a
    job_id -- poll GET /api/optimize/jobs/{job_id} for status/result. This
    is additive: POST /api/optimize above is unchanged and still works
    synchronously with in-process fallback training. Requires a running
    Redis + `rq worker` (see docker-compose.yml's `worker` service) -- a
    job just sits queued forever with no worker running.
    """
    try:
        job_id = enqueue("src.task_jobs.train_optimizer_job", body.alpha, body.beta, body.gamma, body.water_stress)
    except RedisError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job queue unavailable") from exc
    return {"job_id": job_id}


@router.get("/api/optimize/jobs/{job_id}")
async def get_optimize_job(job_id: str, _user: Annotated[User, Depends(require_operator)]) -> dict[str, Any]:
    """Status (queued/started/finished/failed) + result of a job enqueued by
    POST /api/optimize/train_async. 404 for an unknown/expired job id."""
    try:
        return get_status(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from exc
    except RedisError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job queue unavailable") from exc
