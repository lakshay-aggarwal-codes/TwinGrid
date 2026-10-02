"""T9 facility / asset endpoints (roadmap section 9).

Read (viewer or operator):
    GET  /api/facility
    GET  /api/assets?as_of=
    GET  /api/assets/{id}/edges
Write (operator only; viewers get 403):
    POST /api/assets/{id}/move          close current pose, open a new one (idempotent by (asset_id, valid_from))
    POST /api/assets/{id}/edges         open a relationship  (id = the child: child <relation> parent)
    POST /api/edges/{edge_id}/close     close a relationship

All timestamps are ISO-8601. A timestamp without a UTC offset is taken to be UTC.
Coordinates are metres in the facility frame described by ``GET /api/facility`` -> ``frame_note``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, require_operator
from api.rate_limit import limiter
from api.repositories import facility_repository as repo
from api.repositories.facility_repository import utc
from api.services import audit_service, facility_service
from api.services.facility_service import FacilityError
from database import get_db
from models.db_models import Asset, AssetEdge, AssetPose, User

router = APIRouter(tags=["facility"])

_COORD_LIMIT = 1_000_000.0  # metres; rejects absurd values, not a physical claim


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class FacilityOut(BaseModel):
    id: int
    name: str
    frame_unit: str
    frame_note: str
    created_at: datetime


class PoseOut(BaseModel):
    x: float
    y: float
    z: float
    rotation_deg: float
    valid_from: datetime
    valid_to: Optional[datetime]


class LocatedInOut(BaseModel):
    edge_id: int
    parent_asset_id: int
    parent_external_id: Optional[str]
    valid_from: datetime
    valid_to: Optional[datetime]


class AssetOut(BaseModel):
    id: int
    external_id: str
    name: str
    asset_type: str
    retired_at: Optional[datetime]
    pose: Optional[PoseOut]
    located_in: Optional[LocatedInOut]


class AssetsResponse(BaseModel):
    facility_id: int
    frame_unit: str
    as_of: datetime
    count: int
    assets: list[AssetOut]


class AssetRef(BaseModel):
    id: int
    external_id: str
    asset_type: str


class EdgeOut(BaseModel):
    id: int
    relation: str
    parent: AssetRef
    child: AssetRef
    valid_from: datetime
    valid_to: Optional[datetime]


class EdgesResponse(BaseModel):
    asset_id: int
    as_of: datetime
    include_history: bool
    edges: list[EdgeOut]


class MoveRequest(BaseModel):
    x: float = Field(allow_inf_nan=False, ge=-_COORD_LIMIT, le=_COORD_LIMIT)
    y: float = Field(allow_inf_nan=False, ge=-_COORD_LIMIT, le=_COORD_LIMIT)
    z: float = Field(allow_inf_nan=False, ge=-_COORD_LIMIT, le=_COORD_LIMIT)
    rotation_deg: float = Field(default=0.0, allow_inf_nan=False, ge=-360.0, le=360.0)
    valid_from: Optional[datetime] = Field(
        default=None, description="Defaults to now. Idempotency key with the asset id."
    )
    to_parent_id: Optional[int] = Field(default=None, description="Also re-home: new located_in parent (a zone).")


class MoveResponse(BaseModel):
    asset_id: int
    external_id: str
    created: bool
    pose: PoseOut
    located_in: Optional[LocatedInOut]


class EdgeCreateRequest(BaseModel):
    parent_asset_id: int
    relation: str = Field(min_length=1, max_length=16)
    valid_from: Optional[datetime] = None


class EdgeCloseRequest(BaseModel):
    valid_to: Optional[datetime] = None


# --------------------------------------------------------------------------
# Mapping helpers
# --------------------------------------------------------------------------


def _pose_out(p: AssetPose) -> PoseOut:
    return PoseOut(
        x=p.x,
        y=p.y,
        z=p.z,
        rotation_deg=p.rotation_deg,
        valid_from=utc(p.valid_from),  # type: ignore[arg-type]
        valid_to=utc(p.valid_to),
    )


def _located_in_out(e: AssetEdge, parent_external_id: Optional[str]) -> LocatedInOut:
    return LocatedInOut(
        edge_id=e.id,
        parent_asset_id=e.parent_asset_id,
        parent_external_id=parent_external_id,
        valid_from=utc(e.valid_from),  # type: ignore[arg-type]
        valid_to=utc(e.valid_to),
    )


def _ref(a: Asset) -> AssetRef:
    return AssetRef(id=a.id, external_id=a.external_id, asset_type=a.asset_type)


def _raise(exc: FacilityError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# --------------------------------------------------------------------------
# Reads (viewer)
# --------------------------------------------------------------------------


@router.get("/api/facility")
@limiter.limit("30/minute")
async def get_facility(
    request: Request,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    facility_id: Optional[int] = Query(default=None, ge=1),
) -> FacilityOut:
    """The facility and its coordinate-frame definition (default: the lowest-id facility)."""
    try:
        f = await facility_service.get_facility(session, facility_id)
    except FacilityError as exc:
        raise _raise(exc) from exc
    return FacilityOut(
        id=f.id,
        name=f.name,
        frame_unit=f.frame_unit,
        frame_note=f.frame_note,
        created_at=utc(f.created_at),  # type: ignore[arg-type]
    )


@router.get("/api/assets")
@limiter.limit("30/minute")
async def list_assets(
    request: Request,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    as_of: Optional[datetime] = Query(default=None, description="ISO-8601 instant; default now. No offset = UTC."),
    facility_id: Optional[int] = Query(default=None, ge=1),
    asset_type: Optional[str] = Query(default=None, max_length=32),
    include_unplaced: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> AssetsResponse:
    """Assets, poses and located_in parents as they were at ``as_of``."""
    try:
        facility, t, rows = await facility_service.list_assets(
            session,
            facility_id=facility_id,
            as_of=as_of,
            asset_type=asset_type,
            include_unplaced=include_unplaced,
            limit=limit,
            offset=offset,
        )
    except FacilityError as exc:
        raise _raise(exc) from exc

    parents = await repo.get_assets_by_ids(session, sorted({e.parent_asset_id for _, _, e in rows if e is not None}))
    out = [
        AssetOut(
            id=a.id,
            external_id=a.external_id,
            name=a.name,
            asset_type=a.asset_type,
            retired_at=utc(a.retired_at),
            pose=_pose_out(p) if p is not None else None,
            located_in=(
                _located_in_out(e, parents[e.parent_asset_id].external_id if e.parent_asset_id in parents else None)
                if e is not None
                else None
            ),
        )
        for a, p, e in rows
    ]
    return AssetsResponse(facility_id=facility.id, frame_unit=facility.frame_unit, as_of=t, count=len(out), assets=out)


@router.get("/api/assets/{asset_id}/edges")
@limiter.limit("30/minute")
async def list_asset_edges(
    request: Request,
    asset_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    as_of: Optional[datetime] = Query(default=None),
    relation: Optional[str] = Query(default=None, max_length=16),
    include_history: bool = Query(default=False, description="All edges ever recorded; as_of is ignored."),
) -> EdgesResponse:
    """Relationships of an asset (as parent or child) in force at ``as_of``."""
    try:
        t, rows = await facility_service.list_edges(
            session, asset_id=asset_id, as_of=as_of, relation=relation, include_history=include_history
        )
    except FacilityError as exc:
        raise _raise(exc) from exc
    return EdgesResponse(
        asset_id=asset_id,
        as_of=t,
        include_history=include_history,
        edges=[
            EdgeOut(
                id=e.id,
                relation=e.relation,
                parent=_ref(p),
                child=_ref(c),
                valid_from=utc(e.valid_from),  # type: ignore[arg-type]
                valid_to=utc(e.valid_to),
            )
            for e, p, c in rows
        ],
    )


# --------------------------------------------------------------------------
# Writes (operator)
# --------------------------------------------------------------------------


@router.post("/api/assets/{asset_id}/move", response_model=MoveResponse)
@limiter.limit("30/minute")
async def move_asset(
    request: Request,
    response: Response,
    asset_id: int,
    body: MoveRequest,
    user: Annotated[User, Depends(require_operator)],
    session: AsyncSession = Depends(get_db),
) -> MoveResponse:
    """Close the asset's current pose and open a new one. The asset keeps its id and external_id.

    201 when a pose was created; 200 when the request replayed an earlier identical
    ``(asset_id, valid_from)``. 409 on conflict (different content for the same key,
    start not after the current pose, overlapping located_in history).
    """
    try:
        result = await facility_service.move_asset(
            session,
            asset_id=asset_id,
            x=body.x,
            y=body.y,
            z=body.z,
            rotation_deg=body.rotation_deg,
            valid_from=body.valid_from,
            to_parent_id=body.to_parent_id,
        )
    except FacilityError as exc:
        raise _raise(exc) from exc

    asset = await repo.get_asset(session, asset_id)
    assert asset is not None  # move_asset succeeded, so it exists
    parent_ext = None
    if result.edge is not None:
        parents = await repo.get_assets_by_ids(session, [result.edge.parent_asset_id])
        parent_ext = (
            parents[result.edge.parent_asset_id].external_id if result.edge.parent_asset_id in parents else None
        )
    if result.created:
        await audit_service.log_action(
            session,
            action="asset_move",
            user=user,
            resource_type="asset",
            resource_id=asset_id,
            details={
                "external_id": asset.external_id,
                "x": body.x,
                "y": body.y,
                "z": body.z,
                "rotation_deg": body.rotation_deg,
                "valid_from": utc(result.pose.valid_from).isoformat(),  # type: ignore[union-attr]
                "to_parent_id": body.to_parent_id,
            },
            request=request,
        )
    response.status_code = 201 if result.created else 200
    return MoveResponse(
        asset_id=asset.id,
        external_id=asset.external_id,
        created=result.created,
        pose=_pose_out(result.pose),
        located_in=_located_in_out(result.edge, parent_ext) if result.edge is not None else None,
    )


@router.post("/api/assets/{asset_id}/edges", response_model=EdgeOut, status_code=201)
@limiter.limit("30/minute")
async def create_asset_edge(
    request: Request,
    asset_id: int,
    body: EdgeCreateRequest,
    user: Annotated[User, Depends(require_operator)],
    session: AsyncSession = Depends(get_db),
) -> EdgeOut:
    """Open ``asset <relation> parent``. A second open/overlapping located_in is a 409 (use move)."""
    try:
        edge = await facility_service.create_edge(
            session,
            child_asset_id=asset_id,
            parent_asset_id=body.parent_asset_id,
            relation=body.relation,
            valid_from=body.valid_from,
        )
    except FacilityError as exc:
        raise _raise(exc) from exc
    assets = await repo.get_assets_by_ids(session, [edge.parent_asset_id, edge.child_asset_id])
    await audit_service.log_action(
        session,
        action="asset_edge_create",
        user=user,
        resource_type="asset_edge",
        resource_id=edge.id,
        details={"child": edge.child_asset_id, "parent": edge.parent_asset_id, "relation": edge.relation},
        request=request,
    )
    return EdgeOut(
        id=edge.id,
        relation=edge.relation,
        parent=_ref(assets[edge.parent_asset_id]),
        child=_ref(assets[edge.child_asset_id]),
        valid_from=utc(edge.valid_from),  # type: ignore[arg-type]
        valid_to=utc(edge.valid_to),
    )


@router.post("/api/edges/{edge_id}/close", response_model=EdgeOut)
@limiter.limit("30/minute")
async def close_edge(
    request: Request,
    edge_id: int,
    body: EdgeCloseRequest,
    user: Annotated[User, Depends(require_operator)],
    session: AsyncSession = Depends(get_db),
) -> EdgeOut:
    """End a relationship (default: now). History is kept; as-of queries before the end still see it."""
    try:
        edge = await facility_service.close_edge(session, edge_id=edge_id, valid_to=body.valid_to)
    except FacilityError as exc:
        raise _raise(exc) from exc
    assets = await repo.get_assets_by_ids(session, [edge.parent_asset_id, edge.child_asset_id])
    await audit_service.log_action(
        session,
        action="asset_edge_close",
        user=user,
        resource_type="asset_edge",
        resource_id=edge.id,
        details={"valid_to": utc(edge.valid_to).isoformat()},  # type: ignore[union-attr]
        request=request,
    )
    return EdgeOut(
        id=edge.id,
        relation=edge.relation,
        parent=_ref(assets[edge.parent_asset_id]),
        child=_ref(assets[edge.child_asset_id]),
        valid_from=utc(edge.valid_from),  # type: ignore[arg-type]
        valid_to=utc(edge.valid_to),
    )
