"""Plugin: ``GET /api/carbon/schedule`` -- the usual lowest-carbon window for a flexible load (Task 27).

Read-only; nothing is persisted and the digital twin is not run. It reads the same carbon signal the twin uses
(``src.carbon_provider.load_carbon_signal``, memoised) and applies ``src.carbon_schedule.windows``. When the signal is
the flat fallback constant (or any flat series) the answer is "No carbon variation in current data" with no window and
no saving; ``profile=synthetic_demo`` swaps in an explicitly labelled synthetic curve for demonstration. Rate limit:
``RATE_LIMIT_CARBON_SCHEDULE`` (default ``30/minute``, see ``docs/env/Task27.md``).
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from api.auth import get_current_user
from api.rate_limit import limiter
from api.serialization import to_jsonable
from models.db_models import User
from src import carbon_provider
from src.carbon_schedule import windows as W

router = APIRouter(tags=["carbon"])

DEFAULT_LIMIT = "30/minute"
DEFAULT_LOAD_KW = 100.0  # a starting value for the form: the caller's own hypothetical load, not a measurement


def _limit() -> str:
    """Read on every request so a deployment or a test can change it without a reload."""
    return os.getenv("RATE_LIMIT_CARBON_SCHEDULE", "").strip() or DEFAULT_LIMIT


def compute_schedule(
    duration_h: int,
    load_kw: float,
    window_start: int,
    window_hours: int,
    reference_start_hour: int | None,
    profile: str,
) -> dict[str, Any]:
    """May read the carbon file on first use (then memoised): call through ``run_in_threadpool``."""
    return W.suggest(
        carbon_provider.load_carbon_signal(),
        profile=profile,
        duration_h=duration_h,
        load_kw=load_kw,
        window_start=window_start,
        window_hours=window_hours,
        reference_start_hour=reference_start_hour,
    )


@router.get("/api/carbon/schedule")
@limiter.limit(_limit)
async def carbon_schedule(
    request: Request,
    response: Response,
    _user: Annotated[User, Depends(get_current_user)],
    duration_h: int = Query(4, ge=1, le=W.MAX_DURATION_H),
    load_kw: float = Query(DEFAULT_LOAD_KW, gt=0, le=W.MAX_LOAD_KW),
    window_start: int = Query(0, ge=0, le=23),
    window_hours: int = Query(24, ge=1, le=24),
    reference_start_hour: int | None = Query(None, ge=0, le=23),
    profile: Literal["data", "synthetic_demo"] = Query("data"),
) -> dict[str, Any]:
    """Best window for a flexible load of ``duration_h`` hours, from the hour-of-day carbon curve (site-local hours).
    With the flat fallback signal the answer is "No carbon variation in current data" and no saving. Same inputs, same
    answer."""
    try:
        result = await run_in_threadpool(
            compute_schedule, duration_h, load_kw, window_start, window_hours, reference_start_hour, profile
        )
    except W.ScheduleError as exc:  # our own parameter messages; never an internal error text
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return to_jsonable(result)
