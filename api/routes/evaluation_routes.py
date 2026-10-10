from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.rate_limit import http_limit
from api.services import evaluation_service
from models.db_models import User

router = APIRouter(tags=["evaluation"])


@router.get("/api/evaluations", dependencies=[Depends(http_limit("state"))])
async def list_evaluations(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """Policy-evaluation reports found under ``reports/policy_evaluation/`` (BC-11), newest first.

    A read-only projection of files the evaluation harness wrote: nothing is computed, ranked or re-estimated.
    Each item carries the report's own ``outcome`` and ``claim_allowed``. ``NOT_EVALUATED`` / ``none`` means no
    PPO candidate was evaluated. Everything is simulator-only.
    """
    return evaluation_service.list_evaluations()


@router.get("/api/evaluations/{evaluation_id}", dependencies=[Depends(http_limit("state"))])
async def get_evaluation(evaluation_id: str, _user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """One evaluation report: decision, per-policy mean metrics in a fixed order (rule, best_constant, then PPO
    seeds), selection, scenario-set ids and the pre-registration text for metrics and outcomes A/B/C, copied
    verbatim when its hash matches the report. Per-policy means carry no uncertainty; confidence intervals exist
    only inside ``decision.detail`` when PPO candidates were evaluated. 404 for any id that is not a report
    directory."""
    return evaluation_service.get_evaluation(evaluation_id)
