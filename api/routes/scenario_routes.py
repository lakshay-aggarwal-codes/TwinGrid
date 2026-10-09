from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.rate_limit import http_limit
from api.services import scenario_registry
from models.db_models import User

router = APIRouter(tags=["digital-twin"])


@router.get("/api/scenarios", dependencies=[Depends(http_limit("state"))])
async def list_scenarios(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """Registry of named what-if presets (BC-09).

    Each descriptor has an opaque ``id`` and states its ``kind``, ``weather_source`` and ``plant``
    explicitly, plus a parameter schema (bounds and preset values) generated from the same constants
    ``/api/whatif`` enforces. Run one with ``GET /api/whatif?scenario_id=<id>``; parameters the caller
    passes explicitly override the preset. Scenarios are evaluated on the simulated plant only; nothing
    here controls a real facility.
    """
    return scenario_registry.list_scenarios()
