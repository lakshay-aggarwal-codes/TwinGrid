"""T9 DB-level constraint tests (SQLite engine; see report: PostgreSQL run NOT performed here).

These bypass the service layer on purpose: the invariants must hold in the database itself,
so a concurrent writer or a future code path cannot violate them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.db_models import Asset, AssetEdge, AssetPose, Base, Facility, Sensor

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _mk(session, ext, typ):
    f = (await session.execute(select(Facility))).scalars().first()
    if f is None:
        f = Facility(name="F")
        session.add(f)
        await session.flush()
    a = Asset(facility_id=f.id, asset_type=typ, external_id=ext, name=ext)
    session.add(a)
    await session.flush()
    return a


async def test_two_open_located_in_for_one_child_rejected(session):
    z1, z2, r = await _mk(session, "z1", "zone"), await _mk(session, "z2", "zone"), await _mk(session, "r", "rack")
    session.add(AssetEdge(parent_asset_id=z1.id, child_asset_id=r.id, relation="located_in", valid_from=T0))
    await session.flush()
    session.add(
        AssetEdge(parent_asset_id=z2.id, child_asset_id=r.id, relation="located_in", valid_from=T0 + timedelta(days=1))
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_closed_then_open_located_in_allowed(session):
    z1, z2, r = await _mk(session, "z1", "zone"), await _mk(session, "z2", "zone"), await _mk(session, "r", "rack")
    t1 = T0 + timedelta(days=1)
    session.add(
        AssetEdge(parent_asset_id=z1.id, child_asset_id=r.id, relation="located_in", valid_from=T0, valid_to=t1)
    )
    session.add(AssetEdge(parent_asset_id=z2.id, child_asset_id=r.id, relation="located_in", valid_from=t1))
    await session.flush()  # no error


async def test_open_located_in_uniqueness_is_per_child_and_per_relation(session):
    z, r1, r2, pdu = (
        await _mk(session, "z", "zone"),
        await _mk(session, "r1", "rack"),
        await _mk(session, "r2", "rack"),
        await _mk(session, "p", "pdu"),
    )
    session.add_all(
        [
            AssetEdge(parent_asset_id=z.id, child_asset_id=r1.id, relation="located_in", valid_from=T0),
            AssetEdge(
                parent_asset_id=z.id, child_asset_id=r2.id, relation="located_in", valid_from=T0
            ),  # other child: ok
            AssetEdge(
                parent_asset_id=pdu.id, child_asset_id=r1.id, relation="powered_by", valid_from=T0
            ),  # other relation: ok
        ]
    )
    await session.flush()


async def test_edge_interval_and_self_edge_checks(session):
    z, r = await _mk(session, "z", "zone"), await _mk(session, "r", "rack")
    session.add(AssetEdge(parent_asset_id=z.id, child_asset_id=r.id, relation="located_in", valid_from=T0, valid_to=T0))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
    z, r = await _mk(session, "z", "zone"), await _mk(session, "r", "rack")
    session.add(AssetEdge(parent_asset_id=r.id, child_asset_id=r.id, relation="powered_by", valid_from=T0))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_open_pose_per_asset_and_idempotency_key(session):
    r = await _mk(session, "r", "rack")
    session.add(AssetPose(asset_id=r.id, x=0, y=1, z=0, rotation_deg=0, valid_from=T0))
    await session.flush()
    session.add(AssetPose(asset_id=r.id, x=1, y=1, z=0, rotation_deg=0, valid_from=T0 + timedelta(days=1)))
    with pytest.raises(IntegrityError):  # second OPEN pose
        await session.flush()
    await session.rollback()
    r = await _mk(session, "r2", "rack")
    session.add(AssetPose(asset_id=r.id, x=0, y=1, z=0, valid_from=T0, valid_to=T0 + timedelta(days=1)))
    session.add(AssetPose(asset_id=r.id, x=9, y=1, z=0, valid_from=T0, valid_to=T0 + timedelta(days=2)))
    with pytest.raises(IntegrityError):  # same (asset_id, valid_from)
        await session.flush()


async def test_asset_external_id_unique_per_facility(session):
    await _mk(session, "dup", "rack")
    with pytest.raises(IntegrityError):
        await _mk(session, "dup", "rack")


async def test_facility_frame_unit_must_be_metre(session):
    session.add(Facility(name="feet", frame_unit="ft"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_sensor_constraints(session):
    r = await _mk(session, "r", "rack")
    session.add(
        Sensor(asset_id=r.id, measurand="inlet_temperature", unit="degC", sampling_interval_s=0, external_id="s0")
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
    r = await _mk(session, "r", "rack")
    session.add(
        Sensor(
            asset_id=r.id,
            measurand="m",
            unit="degC",
            sampling_interval_s=5,
            external_id="s1",
            min_valid=10,
            max_valid=1,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
