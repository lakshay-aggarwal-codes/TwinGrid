"""Data access for the T9 facility / asset model.

Pure persistence: no business rules, no HTTP. Rules (type validation, move
semantics, overlap policy) live in ``api/services/facility_service.py``.

Time handling
-------------
* Every datetime handed to a query or stored is first normalised by :func:`utc`
  (naive -> assumed UTC, aware -> converted to UTC). SQLite (the test engine)
  returns naive datetimes and ignores tzinfo on bind; PostgreSQL returns aware
  ones. Normalising on the way in keeps both engines consistent.
* Time-bounded rows use HALF-OPEN intervals ``[valid_from, valid_to)``;
  ``valid_to IS NULL`` means "still open". :func:`_in_force` is the single
  definition of "in force at instant t".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.db_models import Asset, AssetEdge, AssetPose, Facility, Sensor


def utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise to timezone-aware UTC. Naive values are taken to already be UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _in_force(model, t: datetime):
    """SQL predicate: row is in force at instant ``t`` (half-open interval)."""
    return and_(model.valid_from <= t, or_(model.valid_to.is_(None), model.valid_to > t))


# --------------------------------------------------------------------------
# Facility
# --------------------------------------------------------------------------


async def get_facility(session: AsyncSession, facility_id: Optional[int] = None) -> Optional[Facility]:
    """The facility with ``facility_id``, or (when None) the lowest-id facility."""
    stmt = select(Facility)
    if facility_id is not None:
        stmt = stmt.where(Facility.id == facility_id)
    else:
        stmt = stmt.order_by(Facility.id).limit(1)
    return (await session.execute(stmt)).scalars().first()


async def get_facility_by_name(session: AsyncSession, name: str) -> Optional[Facility]:
    return (await session.execute(select(Facility).where(Facility.name == name))).scalars().first()


async def insert_facility(session: AsyncSession, *, name: str, frame_note: str = "") -> Facility:
    row = Facility(name=name, frame_unit="m", frame_note=frame_note)
    session.add(row)
    await session.flush()
    return row


async def count_assets(session: AsyncSession, facility_id: int, asset_type: Optional[str] = None) -> int:
    stmt = select(func.count()).select_from(Asset).where(Asset.facility_id == facility_id)
    if asset_type is not None:
        stmt = stmt.where(Asset.asset_type == asset_type)
    return int((await session.execute(stmt)).scalar_one())


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------


async def get_asset(session: AsyncSession, asset_id: int, *, for_update: bool = False) -> Optional[Asset]:
    stmt = select(Asset).where(Asset.id == asset_id)
    if for_update:
        stmt = stmt.with_for_update()  # no-op on SQLite; row lock on PostgreSQL
    return (await session.execute(stmt)).scalars().first()


async def get_assets_by_ids(session: AsyncSession, ids: Sequence[int]) -> dict[int, Asset]:
    if not ids:
        return {}
    rows = (await session.execute(select(Asset).where(Asset.id.in_(list(ids))))).scalars().all()
    return {a.id: a for a in rows}


async def get_asset_by_external_id(session: AsyncSession, facility_id: int, external_id: str) -> Optional[Asset]:
    stmt = select(Asset).where(Asset.facility_id == facility_id, Asset.external_id == external_id)
    return (await session.execute(stmt)).scalars().first()


async def insert_asset(
    session: AsyncSession, *, facility_id: int, asset_type: str, external_id: str, name: str
) -> Asset:
    row = Asset(facility_id=facility_id, asset_type=asset_type, external_id=external_id, name=name)
    session.add(row)
    await session.flush()
    return row


async def list_assets_as_of(
    session: AsyncSession,
    *,
    facility_id: int,
    as_of: datetime,
    asset_type: Optional[str] = None,
    include_unplaced: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> list[tuple[Asset, Optional[AssetPose], Optional[AssetEdge]]]:
    """Assets of a facility as they were at ``as_of``.

    Returns ``(asset, pose_in_force, located_in_edge_in_force)`` tuples ordered by
    asset id. An asset is excluded if it was retired at or before ``as_of``. By
    default only assets that HAD a pose at ``as_of`` are returned (an asset
    created today is not claimed to exist in a past layout); pass
    ``include_unplaced=True`` to also list assets with no pose at that instant.
    """
    t = utc(as_of)
    stmt = select(Asset).where(
        Asset.facility_id == facility_id,
        or_(Asset.retired_at.is_(None), Asset.retired_at > t),
    )
    if asset_type is not None:
        stmt = stmt.where(Asset.asset_type == asset_type)
    if not include_unplaced:
        stmt = stmt.where(exists().where(AssetPose.asset_id == Asset.id, _in_force(AssetPose, t)))
    stmt = stmt.order_by(Asset.id).limit(limit).offset(offset)
    assets = list((await session.execute(stmt)).scalars().all())
    if not assets:
        return []

    ids = [a.id for a in assets]
    poses = {
        p.asset_id: p
        for p in (await session.execute(select(AssetPose).where(AssetPose.asset_id.in_(ids), _in_force(AssetPose, t))))
        .scalars()
        .all()
    }
    edges = {
        e.child_asset_id: e
        for e in (
            await session.execute(
                select(AssetEdge).where(
                    AssetEdge.child_asset_id.in_(ids),
                    AssetEdge.relation == "located_in",
                    _in_force(AssetEdge, t),
                )
            )
        )
        .scalars()
        .all()
    }
    return [(a, poses.get(a.id), edges.get(a.id)) for a in assets]


# --------------------------------------------------------------------------
# Poses
# --------------------------------------------------------------------------


async def get_open_pose(session: AsyncSession, asset_id: int) -> Optional[AssetPose]:
    stmt = select(AssetPose).where(AssetPose.asset_id == asset_id, AssetPose.valid_to.is_(None))
    return (await session.execute(stmt)).scalars().first()


async def get_pose_as_of(session: AsyncSession, asset_id: int, as_of: datetime) -> Optional[AssetPose]:
    stmt = select(AssetPose).where(AssetPose.asset_id == asset_id, _in_force(AssetPose, utc(as_of)))
    return (await session.execute(stmt)).scalars().first()


async def get_pose_by_valid_from(session: AsyncSession, asset_id: int, valid_from: datetime) -> Optional[AssetPose]:
    stmt = select(AssetPose).where(AssetPose.asset_id == asset_id, AssetPose.valid_from == utc(valid_from))
    return (await session.execute(stmt)).scalars().first()


async def list_poses(session: AsyncSession, asset_id: int) -> list[AssetPose]:
    stmt = select(AssetPose).where(AssetPose.asset_id == asset_id).order_by(AssetPose.valid_from)
    return list((await session.execute(stmt)).scalars().all())


async def latest_closed_pose_end(session: AsyncSession, asset_id: int) -> Optional[datetime]:
    stmt = select(func.max(AssetPose.valid_to)).where(AssetPose.asset_id == asset_id)
    return utc((await session.execute(stmt)).scalar_one_or_none())


async def insert_pose(
    session: AsyncSession,
    *,
    asset_id: int,
    x: float,
    y: float,
    z: float,
    rotation_deg: float,
    valid_from: datetime,
) -> AssetPose:
    row = AssetPose(asset_id=asset_id, x=x, y=y, z=z, rotation_deg=rotation_deg, valid_from=utc(valid_from))
    session.add(row)
    await session.flush()
    return row


async def close_pose(session: AsyncSession, pose: AssetPose, valid_to: datetime) -> None:
    pose.valid_to = utc(valid_to)
    await session.flush()


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


async def get_edge(session: AsyncSession, edge_id: int, *, for_update: bool = False) -> Optional[AssetEdge]:
    stmt = select(AssetEdge).where(AssetEdge.id == edge_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalars().first()


async def get_open_located_in(session: AsyncSession, child_asset_id: int) -> Optional[AssetEdge]:
    stmt = select(AssetEdge).where(
        AssetEdge.child_asset_id == child_asset_id,
        AssetEdge.relation == "located_in",
        AssetEdge.valid_to.is_(None),
    )
    return (await session.execute(stmt)).scalars().first()


async def get_located_in_as_of(session: AsyncSession, child_asset_id: int, as_of: datetime) -> Optional[AssetEdge]:
    stmt = select(AssetEdge).where(
        AssetEdge.child_asset_id == child_asset_id,
        AssetEdge.relation == "located_in",
        _in_force(AssetEdge, utc(as_of)),
    )
    return (await session.execute(stmt)).scalars().first()


async def get_open_edge(
    session: AsyncSession, *, child_asset_id: int, parent_asset_id: int, relation: str
) -> Optional[AssetEdge]:
    stmt = select(AssetEdge).where(
        AssetEdge.child_asset_id == child_asset_id,
        AssetEdge.parent_asset_id == parent_asset_id,
        AssetEdge.relation == relation,
        AssetEdge.valid_to.is_(None),
    )
    return (await session.execute(stmt)).scalars().first()


async def located_in_conflicts(
    session: AsyncSession,
    child_asset_id: int,
    valid_from: datetime,
    *,
    exclude_edge_id: Optional[int] = None,
) -> list[AssetEdge]:
    """located_in edges of ``child`` that would overlap a new edge ``[valid_from, +inf)``.

    Existing ``[a, b)`` overlaps ``[valid_from, inf)`` iff ``b IS NULL OR b > valid_from``
    (any ``a`` -- the new edge is unbounded above).
    """
    stmt = select(AssetEdge).where(
        AssetEdge.child_asset_id == child_asset_id,
        AssetEdge.relation == "located_in",
        or_(AssetEdge.valid_to.is_(None), AssetEdge.valid_to > utc(valid_from)),
    )
    if exclude_edge_id is not None:
        stmt = stmt.where(AssetEdge.id != exclude_edge_id)
    return list((await session.execute(stmt)).scalars().all())


async def insert_edge(
    session: AsyncSession,
    *,
    parent_asset_id: int,
    child_asset_id: int,
    relation: str,
    valid_from: datetime,
) -> AssetEdge:
    row = AssetEdge(
        parent_asset_id=parent_asset_id,
        child_asset_id=child_asset_id,
        relation=relation,
        valid_from=utc(valid_from),
    )
    session.add(row)
    await session.flush()
    return row


async def close_edge(session: AsyncSession, edge: AssetEdge, valid_to: datetime) -> None:
    edge.valid_to = utc(valid_to)
    await session.flush()


async def list_edges_for_asset(
    session: AsyncSession,
    asset_id: int,
    *,
    as_of: Optional[datetime] = None,
    relation: Optional[str] = None,
    include_history: bool = False,
    limit: int = 500,
) -> list[tuple[AssetEdge, Asset, Asset]]:
    """Edges where ``asset_id`` is parent OR child, as ``(edge, parent_asset, child_asset)``.

    With ``include_history`` every edge ever recorded is returned (``as_of`` ignored);
    otherwise only edges in force at ``as_of``.
    """
    parent = aliased(Asset)
    child = aliased(Asset)
    stmt = (
        select(AssetEdge, parent, child)
        .join(parent, parent.id == AssetEdge.parent_asset_id)
        .join(child, child.id == AssetEdge.child_asset_id)
        .where(or_(AssetEdge.parent_asset_id == asset_id, AssetEdge.child_asset_id == asset_id))
    )
    if relation is not None:
        stmt = stmt.where(AssetEdge.relation == relation)
    if not include_history:
        if as_of is None:
            raise ValueError("as_of is required unless include_history=True")
        stmt = stmt.where(_in_force(AssetEdge, utc(as_of)))
    stmt = stmt.order_by(AssetEdge.valid_from, AssetEdge.id).limit(limit)
    return [(e, p, c) for e, p, c in (await session.execute(stmt)).all()]


# --------------------------------------------------------------------------
# Sensors (registry only in T9 -- no samples)
# --------------------------------------------------------------------------


async def insert_sensor(
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
    row = Sensor(
        asset_id=asset_id,
        measurand=measurand,
        unit=unit,
        sampling_interval_s=sampling_interval_s,
        external_id=external_id,
        min_valid=min_valid,
        max_valid=max_valid,
    )
    session.add(row)
    await session.flush()
    return row


async def list_sensors_for_asset(
    session: AsyncSession, asset_id: int, *, include_retired: bool = False
) -> Sequence[Sensor]:
    stmt = select(Sensor).where(Sensor.asset_id == asset_id)
    if not include_retired:
        stmt = stmt.where(Sensor.retired_at.is_(None))
    return list((await session.execute(stmt.order_by(Sensor.id))).scalars().all())
