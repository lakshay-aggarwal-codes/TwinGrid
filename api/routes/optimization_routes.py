from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_operator
from api.rate_limit import limiter
from api.repositories import data_repository
from api.schemas.optimization import OptimizeRequest
from api.serialization import to_jsonable
from api.services import optimization_service
from database import get_db
from models.db_models import User

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
    await data_repository.save_optimization_result(
        session,
        alpha=body.alpha, beta=body.beta, gamma=body.gamma,
        water_stress=body.water_stress, hours=body.hours,
        mean_pue=summary["mean_pue"], mean_wue=summary["mean_wue"],
        mean_cooling_power_kw=summary["mean_cooling_power_kw"],
        total_water_consumed_L=summary["total_water_consumed_L"],
        total_reward=summary["total_reward"], safety_violations=summary["safety_violations"],
        results_json=serialized_results,
    )
    return {"results": serialized_results, "summary": summary}