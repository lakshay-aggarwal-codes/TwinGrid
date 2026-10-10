from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from api.auth import get_current_user
from api.rate_limit import http_limit
from api.schemas.runs import RunCreate
from api.services import run_service
from models.db_models import User

router = APIRouter(tags=["runs"])


@router.post(
    "/api/runs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(http_limit("whatif"))],
)
async def submit_run(
    body: RunCreate, response: Response, user: Annotated[User, Depends(get_current_user)]
) -> dict[str, Any]:
    """Submit a scenario from ``GET /api/scenarios`` as a queued run (BC-10).

    ``parameters`` override the scenario preset key by key (descriptor names, bounds as in the registry).
    Returns 202 with the run record (``status: "queued"``); poll ``GET /api/runs/{run_id}``. The run is
    one isolated 24 h what-if on the simulated plant; nothing is persisted in the database and nothing
    reaches a facility. Unknown ``scenario_id`` is 404, out-of-range values 422, queue down 503.
    """
    record = await run_service.submit_run(body, user)
    response.headers["Location"] = f"/api/runs/{record['run_id']}"
    return record


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str, user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """Status of a run: ``queued | running | completed | failed | cancelled``, backend timestamps, and
    ``failure_code`` when failed. ``result_url`` is set only when completed. 404 for an unknown,
    expired or foreign id (readable by the submitter and by operators)."""
    return await run_service.get_run(run_id, user)


@router.get("/api/runs/{run_id}/result")
async def get_run_result(run_id: str, user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """The result of a completed run, carrying its own ``run_id``, ``scenario_id`` and ``scenario_set_id``
    plus provenance (physics version, weather source, plant). 409 until the run is ``completed``."""
    return await run_service.get_run_result(run_id, user)
