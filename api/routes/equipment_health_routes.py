from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.services import equipment_health_service
from models.db_models import User

router = APIRouter(tags=["equipment-health"])


@router.get("/api/equipment/health")
async def equipment_health(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """Predictive-maintenance model's validated methodology performance
    (NASA C-MAPSS proxy dataset -- see dataset_caveat in the response).
    Not live per-rack RUL -- see module docstring in equipment_health_service.py."""
    return equipment_health_service.get_equipment_health_summary()