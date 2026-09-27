from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from api.auth import get_current_user
from api.serialization import to_jsonable
from api.services import esg_report_service, twin_service
from models.db_models import User

router = APIRouter(tags=["esg-report"])


@router.get("/api/esg_report")
async def esg_report(
    _user: Annotated[User, Depends(get_current_user)],
    utilisation: float = Query(0.5, ge=0, le=1),
    outside_temp: float = Query(25.0, ge=-10, le=50),
    water_stress: float = Query(0.0, ge=0, le=1),
) -> FileResponse:
    """Generate and download a one-page ESG/sustainability PDF for the
    current state (see api/services/esg_report_service.py). PDF generation
    is CPU-bound, so it runs in a worker thread."""
    state = to_jsonable(twin_service.compute_state(utilisation, outside_temp, water_stress, "auto"))
    output_path = Path("data/reports/esg_report_latest.pdf")
    await run_in_threadpool(esg_report_service.generate_report, state, output_path)
    return FileResponse(output_path, media_type="application/pdf", filename="twingrid_esg_report.pdf")
