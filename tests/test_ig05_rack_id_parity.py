"""IG-05 / UQ-2 (ADR 005): the rack ``external_id`` the seed writes is the ``rackId`` the frontend renders.

Both sides are executed, not read: the backend ids come from ``scripts/seed_facility.py`` (``build_layout`` and a
real seed into SQLite), the frontend ids from running ``facilityFixtures.ts`` / ``facilityLayout.ts`` with Node.
Skipped (never passed) when Node >= 22.6 is not available.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.db_models import Asset, Base

ROOT = Path(__file__).resolve().parents[1]
THREE = ROOT / "twin-stream-insight-main" / "src" / "three"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
ID_FORMAT = re.compile(r"^zone-\d+-row-\d+-rack-\d+$")


def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_facility_ig05", ROOT / "scripts" / "seed_facility.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_facility_ig05"] = module
    spec.loader.exec_module(module)
    return module


seed = _load_seed()


def _frontend_assets() -> list[dict]:
    """The assets the frontend builds its rack model from (``seedAssets()``), as (type, external_id, parent)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available; cannot execute the frontend fixtures")
    with tempfile.TemporaryDirectory() as d:
        for name in ("facilityLayout.ts", "facilityFixtures.ts"):
            shutil.copy(THREE / name, Path(d) / name)
        (Path(d) / "dump.mts").write_text(
            'import { seedAssets } from "./facilityFixtures.ts";\n'
            "console.log(JSON.stringify(seedAssets(1).map((a) => ({ t: a.asset_type, e: a.external_id, p: a.located_in?.parent_external_id ?? null }))));\n"
        )
        r = subprocess.run(
            [node, "--experimental-strip-types", "dump.mts"], cwd=d, capture_output=True, text=True, timeout=60
        )
    if r.returncode != 0:
        pytest.skip(f"node could not run the frontend fixtures: {r.stderr[-200:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_backend_rack_ids_equal_the_frontend_rack_ids_in_order_with_the_same_zone():
    zones, racks = seed.build_layout()
    fe = _frontend_assets()
    fe_racks = [a for a in fe if a["t"] == "rack"]
    assert [a["e"] for a in fe_racks] == [r.rack_id for r in racks]
    assert [a["p"] for a in fe_racks] == [r.zone_id for r in racks]
    assert [a["e"] for a in fe if a["t"] == "zone"] == [z.zone_id for z in zones]


def test_ids_are_unique_and_well_formed():
    _, racks = seed.build_layout()
    ids = [r.rack_id for r in racks]
    assert len(ids) == len(set(ids)) == 36
    assert all(ID_FORMAT.match(i) for i in ids)


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)() as s:
        yield s
    await eng.dispose()


async def test_ids_stored_by_the_real_seed_equal_the_frontend_rack_ids(session):
    await seed.seed_default_facility(session, scale=1.0, valid_from=T0)
    await session.commit()
    stored = (await session.execute(select(Asset.external_id).where(Asset.asset_type == "rack"))).scalars().all()
    fe = {a["e"] for a in _frontend_assets() if a["t"] == "rack"}
    assert set(stored) == fe and len(stored) == 36
