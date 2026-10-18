"""Plugin: optimizer recommendation, sandbox and approvals (Task 19).

* ``GET  /api/optimizer/baseline-recommendation`` -- any signed-in user. The best available BASELINE controller
  (stored validation reward, see ``src/baseline_recommendation.py``), its proposed set-points for the given context, and
  the twin-simulated effect vs the current settings. Not PPO, and says so.
* ``GET  /api/optimizer/sandbox`` -- any signed-in user. The same prediction for set-points of your choosing. Read-only
  (ADR 007): nothing is persisted.
* ``POST /api/optimizer/proposals`` -- operator or admin. Records a proposal (pending). The server recomputes the
  prediction itself and refuses a proposal whose simulated outlet temperature exceeds the limit.
* ``GET  /api/optimizer/proposals`` -- any signed-in user.
* ``POST /api/optimizer/proposals/{id}/decision`` -- admin only, and never the proposer. Approve or reject, once.

Approval records a decision; nothing is applied to equipment. Rows are written by ``proposal_repository``; each change
writes one atomic audit row (``optimizer_proposal_created`` / ``_approved`` / ``_rejected``; not added to
``audit_service.EVENT_MODES``, which a test pins). Rate limit: the existing ``optimize`` class for writes, ``whatif``
for the two computations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.errors import ApiError
from api.rate_limit import http_limit, run_compute
from api.repositories import proposal_repository
from api.serialization import to_jsonable
from api.services import audit_service, twin_service
from api.services import scenario_registry as SR
from database import get_db
from models.db_models import OptimizerProposal, User
from src import baseline_recommendation as br
from src import optimizer_proposals as rules
from src.digital_twin import OUTLET_TEMP_MAX

router = APIRouter(tags=["optimizer"])

ROOT = Path(__file__).resolve().parents[2]
Mode = Literal["free_air", "closed_loop", "evaporative", "hybrid"]
CurrentMode = Literal["auto", "free_air", "closed_loop", "evaporative", "hybrid"]


class Context(BaseModel):
    """The conditions a prediction is made for, and the current settings it is compared with."""

    model_config = ConfigDict(extra="forbid")

    utilisation: float = Field(
        SR.WHATIF_DEFAULTS["utilisation"], ge=SR.UTILISATION_BOUNDS[0], le=SR.UTILISATION_BOUNDS[1]
    )
    outside_temp: float = Field(
        SR.WHATIF_DEFAULTS["outside_temp"], ge=SR.OUTSIDE_TEMP_BOUNDS[0], le=SR.OUTSIDE_TEMP_BOUNDS[1]
    )
    water_stress: float = Field(
        SR.WHATIF_DEFAULTS["water_stress"], ge=SR.WATER_STRESS_BOUNDS[0], le=SR.WATER_STRESS_BOUNDS[1]
    )
    current_mode: CurrentMode = "auto"
    current_chilled_water_temp: float = Field(
        SR.WHATIF_DEFAULTS["chilled_water_temp"], ge=SR.CHILLED_WATER_TEMP_BOUNDS[0], le=SR.CHILLED_WATER_TEMP_BOUNDS[1]
    )
    inlet_temp_c: Optional[float] = Field(None, ge=0, le=60)


def _accepted_range() -> tuple[float, float]:
    """Read per request: the physics (``PHYSICS_VERSION``) is not fixed at import."""
    return rules.accepted_chilled_range_C(SR.CHILLED_WATER_TEMP_BOUNDS)


def _check_setpoint(value: float) -> float:
    lo, hi = _accepted_range()
    if not lo <= value <= hi:
        raise ValueError(f"must be between {lo:g} and {hi:g} C for the running physics")
    return value


class ProposalCreate(Context):
    chilled_water_temp_c: float
    cooling_mode: Mode
    rationale: Optional[str] = Field(None, max_length=rules.MAX_NOTE_CHARS)

    _in_range = field_validator("chilled_water_temp_c")(_check_setpoint)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    note: Optional[str] = Field(None, max_length=rules.MAX_NOTE_CHARS)


# ----------------------------------------------------------------------------- computation (blocking)


def _predict(ctx: Context, chilled_c: float, mode: str) -> dict[str, Any]:
    reference = twin_service.compute_whatif(
        ctx.utilisation, ctx.outside_temp, ctx.water_stress, ctx.current_mode, ctx.current_chilled_water_temp
    )
    proposed = twin_service.compute_whatif(ctx.utilisation, ctx.outside_temp, ctx.water_stress, mode, chilled_c)
    effect = rules.predicted_effect(reference, proposed, OUTLET_TEMP_MAX)
    # additive: which side of the evaluated actuator range each set-point is on, and under which physics
    effect["setpoint_check"] = rules.setpoint_check(chilled_c, ctx.current_chilled_water_temp)
    return effect


def _recommend(ctx: Context) -> dict[str, Any]:
    return br.recommend(
        ROOT,
        outside_temp=ctx.outside_temp,
        water_stress=ctx.water_stress,
        current_chilled_c=ctx.current_chilled_water_temp,
        inlet_temp_c=ctx.inlet_temp_c,
    )


def compute_recommendation(ctx: Context) -> dict[str, Any]:
    rec = _recommend(ctx)
    sel = rec["selected"]
    predicted = _predict(ctx, sel["chilled_water_temp_C"], sel["cooling_mode"]) if sel else None
    return {"recommendation": rec, "predicted": predicted, "persisted": False}


def _same_setpoints(sel: Optional[dict[str, Any]], chilled_c: float, mode: str) -> bool:
    return sel is not None and abs(sel["chilled_water_temp_C"] - chilled_c) < 0.01 and sel["cooling_mode"] == mode


def compute_proposal(body: ProposalCreate) -> tuple[str, dict[str, Any]]:
    """(source, prediction). The source is the baseline only if the set-points are exactly its recommendation."""
    sel = _recommend(body)["selected"]
    same = _same_setpoints(sel, body.chilled_water_temp_c, body.cooling_mode)
    source = f"baseline:{sel['name']}" if same else "manual"
    return source, _predict(body, body.chilled_water_temp_c, body.cooling_mode)


# ----------------------------------------------------------------------------- roles


async def _deny(user: User, request: Request, required: str) -> None:
    await audit_service.log_action_best_effort(
        action="permission_denied",
        user=user,
        resource_type="endpoint",
        resource_id=f"{request.method} {request.url.path}",
        details={"required_role": required, "actual_role": user.role},
        request=request,
        outcome=audit_service.AUDIT_OUTCOME_DENIED,
    )
    raise ApiError(403, "forbidden", f"{required.capitalize()} role required")


async def require_proposer(request: Request, user: Annotated[User, Depends(get_current_user)]) -> User:
    if not rules.can_propose(user.role):
        await _deny(user, request, "operator")
    return user


async def require_admin(request: Request, user: Annotated[User, Depends(get_current_user)]) -> User:
    if not rules.can_decide(user.role):
        await _deny(user, request, "admin")
    return user


# ----------------------------------------------------------------------------- serialisation


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def proposal_to_dict(p: OptimizerProposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "created_at": _iso(p.created_at),
        "proposer": p.proposer,
        "source": p.source,
        "chilled_water_temp_C": p.chilled_water_temp_c,
        "cooling_mode": p.cooling_mode,
        "context": p.context,
        "predicted": p.predicted,
        "rationale": p.rationale,
        "origin": p.origin,
        "status": p.status,
        "decided_by": p.decided_by,
        "decided_at": _iso(p.decided_at),
        "decision_note": p.decision_note,
        "approval_label": rules.APPROVAL_LABEL,
    }


# ----------------------------------------------------------------------------- routes


@router.get("/api/optimizer/baseline-recommendation", dependencies=[Depends(http_limit("whatif"))])
async def baseline_recommendation(
    _user: Annotated[User, Depends(get_current_user)], ctx: Annotated[Context, Query()]
) -> dict[str, Any]:
    return to_jsonable(await run_compute(compute_recommendation, ctx))


class SandboxQuery(Context):
    proposed_chilled_water_temp: float
    proposed_mode: Mode

    _in_range = field_validator("proposed_chilled_water_temp")(_check_setpoint)


@router.get("/api/optimizer/sandbox", dependencies=[Depends(http_limit("whatif"))])
async def sandbox(
    _user: Annotated[User, Depends(get_current_user)], q: Annotated[SandboxQuery, Query()]
) -> dict[str, Any]:
    predicted = await run_compute(_predict, q, q.proposed_chilled_water_temp, q.proposed_mode)
    return to_jsonable({"predicted": predicted, "persisted": False})


@router.post("/api/optimizer/proposals", status_code=201, dependencies=[Depends(http_limit("optimize"))])
async def create_proposal(
    body: ProposalCreate,
    request: Request,
    user: Annotated[User, Depends(require_proposer)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    source, predicted = await run_compute(compute_proposal, body)
    predicted = to_jsonable(predicted)
    if not predicted["within_outlet_limit"]:
        raise ApiError(422, "unsafe_prediction", "The simulated outlet temperature exceeds the limit; not recorded")
    rationale = body.rationale.strip() if body.rationale else None
    row = await proposal_repository.create_proposal(
        session,
        proposer=user.username,
        source=source,
        chilled_water_temp_c=body.chilled_water_temp_c,
        cooling_mode=body.cooling_mode,
        context=body.model_dump(exclude={"chilled_water_temp_c", "cooling_mode", "rationale"}),
        predicted=predicted,
        rationale=rationale or None,
    )
    await audit_service.log_action(
        session,
        action="optimizer_proposal_created",
        user=user,
        resource_type="optimizer_proposal",
        resource_id=row.id,
        details={
            "source": source,
            "chilled_water_temp_C": body.chilled_water_temp_c,
            "cooling_mode": body.cooling_mode,
            "within_outlet_limit": predicted["within_outlet_limit"],
        },
        request=request,
    )
    return proposal_to_dict(row)


@router.get("/api/optimizer/proposals")
async def list_proposals(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    status: Optional[Literal["pending", "approved", "rejected"]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    return [proposal_to_dict(p) for p in await proposal_repository.list_proposals(session, limit, status)]


@router.post("/api/optimizer/proposals/{proposal_id}/decision", dependencies=[Depends(http_limit("optimize"))])
async def decide_proposal(
    proposal_id: int,
    body: Decision,
    request: Request,
    user: Annotated[User, Depends(require_admin)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    note = body.note.strip() if body.note else None
    try:
        row = await proposal_repository.decide(
            session, proposal_id, decider=user.username, decision=body.decision, note=note or None
        )
    except rules.DecisionError as exc:
        if exc.code == "self_decision":
            await audit_service.log_action_best_effort(
                action="permission_denied",
                user=user,
                resource_type="optimizer_proposal",
                resource_id=proposal_id,
                details={"reason": "self_decision"},
                request=request,
                outcome=audit_service.AUDIT_OUTCOME_DENIED,
            )
            raise ApiError(403, "self_decision", "You cannot decide a proposal you made yourself") from exc
        raise ApiError(409, "not_pending", "This proposal has already been decided") from exc
    if row is None:
        raise ApiError(404, "not_found", "Proposal not found")
    await audit_service.log_action(
        session,
        action=f"optimizer_proposal_{row.status}",
        user=user,
        resource_type="optimizer_proposal",
        resource_id=row.id,
        details={
            "decision": body.decision,
            "source": row.source,
            "chilled_water_temp_C": row.chilled_water_temp_c,
            "cooling_mode": row.cooling_mode,
            "note_added": note is not None,
        },
        request=request,
    )
    return proposal_to_dict(row)
