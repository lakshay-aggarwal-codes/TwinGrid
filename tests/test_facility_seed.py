"""T9 seed tests: the seed must match the REAL frontend layout, not our reading of it."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.services import facility_service as svc
from models.db_models import Asset, Base

ROOT = Path(__file__).resolve().parents[1]


def _load_seed_module():
    """Load scripts/seed_facility.py by path (scripts/ is not a package, so a plain import is unresolvable)."""
    path = ROOT / "scripts" / "seed_facility.py"
    spec = importlib.util.spec_from_file_location("seed_facility", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_facility"] = module  # required before exec: its dataclasses look themselves up here
    spec.loader.exec_module(module)
    return module


seed = _load_seed_module()

LAYOUT_TS = ROOT / "twin-stream-insight-main" / "src" / "three" / "facilityLayout.ts"
TOL = 1e-6
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _real_layout() -> dict:
    """Execute the actual facilityLayout.ts with Node (>= 22.6, type stripping)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available; cannot execute facilityLayout.ts")
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(LAYOUT_TS, Path(d) / "facilityLayout.mts")
        (Path(d) / "dump.mts").write_text(
            'import { FACILITY_LAYOUT } from "./facilityLayout.mts";\nconsole.log(JSON.stringify(FACILITY_LAYOUT));\n'
        )
        r = subprocess.run(
            [node, "--experimental-strip-types", "dump.mts"], cwd=d, capture_output=True, text=True, timeout=60
        )
    if r.returncode != 0:
        pytest.skip(f"node could not run the TS layout: {r.stderr[-200:]}")
    return json.loads(r.stdout)


def test_python_mirror_matches_real_frontend_layout():
    real = _real_layout()
    zones, racks = seed.build_layout()
    assert (len(zones), len(racks)) == (len(real["zones"]), len(real["racks"])) == (3, 36)
    for mine, theirs in zip(racks, real["racks"]):
        assert (mine.rack_id, mine.zone_id, mine.row_id) == (theirs["rackId"], theirs["zoneId"], theirs["rowId"])
        assert all(abs(a - b) < TOL for a, b in zip(mine.position, theirs["position"]))
        assert all(abs(a - b) < TOL for a, b in zip(mine.size, theirs["size"]))
    for mine, theirs in zip(zones, real["zones"]):
        assert mine.zone_id == theirs["zoneId"] and mine.label == theirs["label"]
        assert (
            abs(mine.center_x - theirs["bounds"]["centerX"]) < TOL
            and abs(mine.center_z - theirs["bounds"]["centerZ"]) < TOL
        )


def test_layout_geometry_facts_behind_the_scale_proposal():
    """Pins the numbers the 1 unit = 1 m proposal rests on; if the frontend layout changes, re-verify."""
    _, racks = seed.build_layout()
    assert {r.size for r in racks} == {(0.6, 2.0, 1.0)}
    row1 = [r for r in racks if r.zone_id == "zone-1" and r.row_id == "row-1"]
    assert round(row1[1].position[0] - row1[0].position[0], 9) == 0.95
    assert {round(r.position[2], 9) for r in racks} == {-1.7, 1.7}


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)() as s:
        yield s
    await eng.dispose()


async def test_seed_yields_36_racks_matching_layout_with_preserved_ids(session):
    summary = await seed.seed_default_facility(session, scale=1.0, valid_from=T0)
    await session.commit()
    assert (summary.zones, summary.racks) == (3, 36)
    real = _real_layout()
    facility, t, rows = await svc.list_assets(session, as_of=T0, asset_type="rack", now=T0)
    assert len(rows) == 36
    by_ext = {a.external_id: (p, e) for a, p, e in rows}
    zone_ext = {
        a.id: a.external_id for a in (await session.execute(select(Asset).where(Asset.asset_type == "zone"))).scalars()
    }
    for rack in real["racks"]:
        pose, edge = by_ext[rack["rackId"]]
        assert (pose.x, pose.y, pose.z) == pytest.approx(tuple(rack["position"]), abs=TOL)  # scale 1.0
        assert zone_ext[edge.parent_asset_id] == rack["zoneId"]
    assert facility.frame_unit == "m" and "1.0 m per scene unit" in facility.frame_note


async def test_seed_applies_scale_factor(session):
    await seed.seed_default_facility(session, scale=0.5, valid_from=T0)
    _, _, rows = await svc.list_assets(session, as_of=T0, asset_type="rack", now=T0)
    first = next(p for a, p, _ in rows if a.external_id == "zone-1-row-1-rack-1")
    assert (first.x, first.y, first.z) == pytest.approx((0.15, 0.5, -0.85), abs=TOL)


async def test_seed_refuses_second_run_and_bad_scale(session):
    await seed.seed_default_facility(session, scale=1.0, valid_from=T0)
    with pytest.raises(RuntimeError):
        await seed.seed_default_facility(session, scale=1.0, valid_from=T0)
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            await seed.seed_default_facility(session, scale=bad, valid_from=T0)


async def test_seeded_rack_move_keeps_identity(session):
    await seed.seed_default_facility(session, scale=1.0, valid_from=T0)
    await session.commit()
    rack = (await session.execute(select(Asset).where(Asset.external_id == "zone-3-row-2-rack-6"))).scalar_one()
    rack_id, ext = rack.id, rack.external_id
    t1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
    zone1 = (await session.execute(select(Asset).where(Asset.external_id == "zone-1"))).scalar_one()
    await svc.move_asset(session, asset_id=rack_id, x=3.0, y=1.0, z=0.0, valid_from=t1, to_parent_id=zone1.id, now=t1)
    await session.commit()
    assert (await session.get(Asset, rack_id)).external_id == ext
    assert (
        await session.execute(select(func.count()).select_from(Asset).where(Asset.asset_type == "rack"))
    ).scalar_one() == 36
    _, _, old = await svc.list_assets(session, as_of=t1.replace(day=15, month=1), asset_type="rack", now=t1)
    _, _, new = await svc.list_assets(session, as_of=t1, asset_type="rack", now=t1)

    def f(rows):
        return next((p, e) for a, p, e in rows if a.id == rack_id)

    assert f(old)[0].x == pytest.approx(22.75) and f(new)[0].x == 3.0
    assert f(old)[1].parent_asset_id != f(new)[1].parent_asset_id == zone1.id
