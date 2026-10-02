"""Business rules for the T9 facility / asset model.

Rules enforced here (the DB enforces the structural ones too -- partial unique
indexes and CHECKs in migration M3 -- so a race cannot slip past this layer):

* ``asset_type`` and ``relation`` are validated TEXT (no DB enum, no migration
  to add a type): see ASSET_TYPES / RELATIONS.
* Edges read "child <relation> parent" (rack located_in zone, crac serves zone,
  rack powered_by pdu).
* A child has at most one open ``located_in`` edge, and no two ``located_in``
  intervals for one child overlap.
* Moving an asset closes its open pose and opens a new one at the same instant
  (half-open intervals, so there is neither gap nor overlap). The asset row --
  id, external_id, name -- is never touched, so identity survives every move.
* Moves are idempotent by ``(asset_id, valid_from)``: replaying the same request
  returns the existing pose; the same key with different content is a conflict.
* History is append-only in effect: a move may not start before the current
  pose started, and may not be dated in the future (beyond a small clock skew).

All validation runs before any write, so a rejected request changes nothing.
Writes only ``flush``; the request-scoped session (database.get_session)
commits on success and rolls back on any exception.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories import facility_repository as repo
from api.repositories.facility_repository import utc
from models.db_models import Asset, AssetEdge, AssetPose, Facility, Sensor

# Validated text, not DB enums: adding a type is a one-line change here, no migration.
ASSET_TYPES: frozenset[str] = frozenset({"zone", "rack", "crac", "chiller", "cooling_tower", "pdu", "ups"})
RELATIONS: frozenset[str] = frozenset({"located_in", "serves", "powered_by"})

_COOLING_TYPES = frozenset({"crac", "chiller", "cooling_tower"})
_POWER_TYPES = frozenset({"pdu", "ups"})

# Largest tolerated gap between a client-supplied valid_from/valid_to and server "now".
FUTURE_SKEW = timedelta(seconds=5)

_POSE_ABS_TOL = 1e-9


class FacilityError(Exception):
    """Base class; ``status_code`` is the HTTP status the route layer maps it to."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(FacilityError):
    status_code = 404


class ConflictError(FacilityError):
    status_code = 409


class ValidationError(FacilityError):
    status_code = 422


@dataclass(frozen=True)
class MoveResult:
    pose: AssetPose
    edge: Optional[AssetEdge]  # located_in edge in force after the move (None if parent not addressed)
    created: bool  # False => idempotent replay of an earlier identical request


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------


def validate_asset_type(asset_type: str) -> str:
    if asset_type not in ASSET_TYPES:
        raise ValidationError(f"unknown asset_type {asset_type!r}; allowed: {sorted(ASSET_TYPES)}")
    return asset_type


def validate_relation(relation: str) -> str:
    if relation not in RELATIONS:
        raise ValidationError(f"unknown relation {relation!r}; allowed: {sorted(RELATIONS)}")
    return relation


def _now(now: Optional[datetime]) -> datetime:
    return utc(now) if now is not None else datetime.now(timezone.utc)


def _resolve_instant(value: Optional[datetime], now: datetime, field: str) -> datetime:
    instant = utc(value) if value is not None else now
    if instant > now + FUTURE_SKEW:
        raise ValidationError(f"{field} may not be in the future")
    return instant


def _check_finite(**values: float) -> None:
    for name, v in values.items():
        if not math.isfinite(v):
            raise ValidationError(f"{name} must be a finite number")


def _check_edge_types(relation: str, parent: Asset, child: Asset) -> None:
    if parent.id == child.id:
        raise ValidationError("an asset cannot be related to itself")
    if parent.facility_id != child.facility_id:
        raise ValidationError("both assets must belong to the same facility")
    if parent.retired_at is not None or child.retired_at is not None:
        raise ConflictError("retired assets cannot take part in new relationships")
    if relation == "located_in":
        if parent.asset_type != "zone":
            raise ValidationError("located_in parent must be a zone")
        if child.asset_type == "zone":
            raise ValidationError("a zone cannot be located_in another asset")
    elif relation == "powered_by":
        if parent.asset_type not in _POWER_TYPES:
            raise ValidationError(f"powered_by parent must be one of {sorted(_POWER_TYPES)}")
        if child.asset_type == "zone":
            raise ValidationError("a zone cannot be powered_by an asset")
    elif relation == "serves":
        if child.asset_type not in _COOLING_TYPES:
            raise ValidationError(f"the serving asset (child) must be one of {sorted(_COOLING_TYPES)}")


def _same_pose(p: AssetPose, x: float, y: float, z: float, rotation_deg: float) -> bool:
    return all(
        math.isclose(a, b, abs_tol=_POSE_ABS_TOL)
        for a, b in ((p.x, x), (p.y, y), (p.z, z), (p.rotation_deg, rotation_deg))
    )


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


async def get_facility(session: AsyncSession, facility_id: Optional[int] = None) -> Facility:
    facility = await repo.get_facility(session, facility_id)
    if facility is None:
        raise NotFoundError("facility not found")
    return facility


async def list_assets(
    session: AsyncSession,
    *,
    facility_id: Optional[int] = None,
    as_of: Optional[datetime] = None,
    asset_type: Optional[str] = None,
    include_unplaced: bool = False,
    limit: int = 500,
    offset: int = 0,
    now: Optional[datetime] = None,
) -> tuple[Facility, datetime, list[tuple[Asset, Optional[AssetPose], Optional[AssetEdge]]]]:
    """Topology + poses as of an instant. Returns ``(facility, effective_as_of, rows)``."""
    facility = await get_facility(session, facility_id)
    if asset_type is not None:
        validate_asset_type(asset_type)
    t = utc(as_of) if as_of is not None else _now(now)
    rows = await repo.list_assets_as_of(
        session,
        facility_id=facility.id,
        as_of=t,
        asset_type=asset_type,
        include_unplaced=include_unplaced,
        limit=limit,
        offset=offset,
    )
    return facility, t, rows


async def list_edges(
    session: AsyncSession,
    *,
    asset_id: int,
    as_of: Optional[datetime] = None,
    relation: Optional[str] = None,
    include_history: bool = False,
    now: Optional[datetime] = None,
) -> tuple[datetime, list[tuple[AssetEdge, Asset, Asset]]]:
    if await repo.get_asset(session, asset_id) is None:
        raise NotFoundError(f"asset {asset_id} not found")
    if relation is not None:
        validate_relation(relation)
    t = utc(as_of) if as_of is not None else _now(now)
    rows = await repo.list_edges_for_asset(
        session, asset_id, as_of=t, relation=relation, include_history=include_history
    )
    return t, rows


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------


async def create_asset(
    session: AsyncSession, *, facility_id: int, asset_type: str, external_id: str, name: str
) -> Asset:
    validate_asset_type(asset_type)
    if not external_id.strip() or not name.strip():
        raise ValidationError("external_id and name must be non-empty")
    if await repo.get_facility(session, facility_id) is None:
        raise NotFoundError(f"facility {facility_id} not found")
    if await repo.get_asset_by_external_id(session, facility_id, external_id) is not None:
        raise ConflictError(f"asset external_id {external_id!r} already exists in this facility")
    try:
        return await repo.insert_asset(
            session, facility_id=facility_id, asset_type=asset_type, external_id=external_id, name=name
        )
    except IntegrityError as exc:
        raise ConflictError(f"asset external_id {external_id!r} already exists in this facility") from exc


async def create_sensor(
    session: AsyncSession,
    *,
    asset_id: int,
    measurand: str,
    unit: str,
    sampling_interval_s: float,
    external_id: str,
    min_valid: Optional[float] = None,
    max_valid: Optional[float] = None,
) -> Sensor:
    """Register a sensor on an asset. Registry only: T9 stores no samples."""
    asset = await repo.get_asset(session, asset_id)
    if asset is None:
        raise NotFoundError(f"asset {asset_id} not found")
    if asset.retired_at is not None:
        raise ConflictError("cannot attach a sensor to a retired asset")
    _check_finite(sampling_interval_s=sampling_interval_s)
    if sampling_interval_s <= 0:
        raise ValidationError("sampling_interval_s must be > 0")
    for name, v in (("min_valid", min_valid), ("max_valid", max_valid)):
        if v is not None:
            _check_finite(**{name: v})
    if min_valid is not None and max_valid is not None and min_valid > max_valid:
        raise ValidationError("min_valid must be <= max_valid")
    try:
        return await repo.insert_sensor(
            session,
            asset_id=asset_id,
            measurand=measurand,
            unit=unit,
            sampling_interval_s=sampling_interval_s,
            external_id=external_id,
            min_valid=min_valid,
            max_valid=max_valid,
        )
    except IntegrityError as exc:
        raise ConflictError(f"sensor external_id {external_id!r} already exists") from exc


async def move_asset(
    session: AsyncSession,
    *,
    asset_id: int,
    x: float,
    y: float,
    z: float,
    rotation_deg: float = 0.0,
    valid_from: Optional[datetime] = None,
    to_parent_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> MoveResult:
    """Close the asset's open pose and open a new one; optionally re-home it.

    If ``to_parent_id`` is given and differs from the asset's current located_in
    parent, the open located_in edge is closed and a new one opened at the same
    instant. The asset row itself is never modified (identity preserved).
    """
    _check_finite(x=x, y=y, z=z, rotation_deg=rotation_deg)
    now_ = _now(now)
    vf = _resolve_instant(valid_from, now_, "valid_from")

    asset = await repo.get_asset(session, asset_id, for_update=True)
    if asset is None:
        raise NotFoundError(f"asset {asset_id} not found")
    if asset.retired_at is not None:
        raise ConflictError("retired assets cannot be moved")

    # ---- validate everything before writing anything ------------------------
    parent: Optional[Asset] = None
    if to_parent_id is not None:
        if asset.asset_type == "zone":
            raise ValidationError("a zone has no parent; omit to_parent_id")
        parent = await repo.get_asset(session, to_parent_id)
        if parent is None:
            raise NotFoundError(f"parent asset {to_parent_id} not found")
        _check_edge_types("located_in", parent, asset)

    # Idempotent replay / key conflict on (asset_id, valid_from).
    existing = await repo.get_pose_by_valid_from(session, asset_id, vf)
    if existing is not None:
        if not _same_pose(existing, x, y, z, rotation_deg):
            raise ConflictError("a different pose already starts at this valid_from for this asset")
        edge_now = await repo.get_located_in_as_of(session, asset_id, vf)
        if parent is not None and (edge_now is None or edge_now.parent_asset_id != parent.id):
            raise ConflictError("a pose already starts at this valid_from with a different parent")
        return MoveResult(pose=existing, edge=edge_now, created=False)

    open_pose = await repo.get_open_pose(session, asset_id)
    if open_pose is not None:
        if vf <= utc(open_pose.valid_from):
            raise ConflictError("valid_from must be later than the start of the current pose")
    else:
        last_end = await repo.latest_closed_pose_end(session, asset_id)
        if last_end is not None and vf < last_end:
            raise ConflictError("valid_from overlaps earlier pose history")

    edge_to_close: Optional[AssetEdge] = None
    open_edge: Optional[AssetEdge] = None
    open_new_edge = False
    if parent is not None:
        open_edge = await repo.get_open_located_in(session, asset_id)
        if open_edge is None or open_edge.parent_asset_id != parent.id:
            if open_edge is not None and vf <= utc(open_edge.valid_from):
                raise ConflictError("valid_from must be later than the start of the current located_in edge")
            conflicts = await repo.located_in_conflicts(
                session, asset_id, vf, exclude_edge_id=open_edge.id if open_edge is not None else None
            )
            if conflicts:
                raise ConflictError("new located_in edge would overlap existing located_in history")
            edge_to_close = open_edge
            open_new_edge = True

    # ---- writes (close before open: the partial unique indexes allow one open row) ----
    try:
        if open_pose is not None:
            await repo.close_pose(session, open_pose, vf)
        pose = await repo.insert_pose(
            session, asset_id=asset_id, x=x, y=y, z=z, rotation_deg=rotation_deg, valid_from=vf
        )
        edge = open_edge
        if open_new_edge:
            if edge_to_close is not None:
                await repo.close_edge(session, edge_to_close, vf)
            edge = await repo.insert_edge(
                session,
                parent_asset_id=parent.id,  # type: ignore[union-attr]  # parent set whenever open_new_edge
                child_asset_id=asset_id,
                relation="located_in",
                valid_from=vf,
            )
        elif parent is None:
            edge = await repo.get_open_located_in(session, asset_id)
    except IntegrityError as exc:  # concurrent writer won the race on a unique index
        raise ConflictError("concurrent modification detected; retry") from exc
    return MoveResult(pose=pose, edge=edge, created=True)


async def create_edge(
    session: AsyncSession,
    *,
    child_asset_id: int,
    parent_asset_id: int,
    relation: str,
    valid_from: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> AssetEdge:
    """Open a relationship ``child <relation> parent`` (open-ended; close it with :func:`close_edge`).

    A second ``located_in`` for a child that already has an open or overlapping one is
    rejected (409): relocating a rack is done with :func:`move_asset`.
    """
    validate_relation(relation)
    now_ = _now(now)
    vf = _resolve_instant(valid_from, now_, "valid_from")

    child = await repo.get_asset(session, child_asset_id, for_update=True)
    if child is None:
        raise NotFoundError(f"asset {child_asset_id} not found")
    parent = await repo.get_asset(session, parent_asset_id)
    if parent is None:
        raise NotFoundError(f"asset {parent_asset_id} not found")
    _check_edge_types(relation, parent, child)

    if (
        await repo.get_open_edge(session, child_asset_id=child.id, parent_asset_id=parent.id, relation=relation)
        is not None
    ):
        raise ConflictError("an identical open relationship already exists")
    if relation == "located_in" and await repo.located_in_conflicts(session, child.id, vf):
        raise ConflictError(
            "asset already has an open or overlapping located_in edge; use POST /api/assets/{id}/move to relocate it"
        )
    try:
        return await repo.insert_edge(
            session, parent_asset_id=parent.id, child_asset_id=child.id, relation=relation, valid_from=vf
        )
    except IntegrityError as exc:
        raise ConflictError("relationship conflicts with an existing open edge") from exc


async def close_edge(
    session: AsyncSession,
    *,
    edge_id: int,
    valid_to: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> AssetEdge:
    now_ = _now(now)
    edge = await repo.get_edge(session, edge_id, for_update=True)
    if edge is None:
        raise NotFoundError(f"edge {edge_id} not found")
    if edge.valid_to is not None:
        raise ConflictError("edge is already closed")
    vt = _resolve_instant(valid_to, now_, "valid_to")
    if vt <= utc(edge.valid_from):
        raise ValidationError("valid_to must be later than the edge's valid_from")
    await repo.close_edge(session, edge, vt)
    return edge
