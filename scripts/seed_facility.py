#!/usr/bin/env python3
"""One-time seed (T9): the default facility, 3 zones and 36 racks, from the frontend layout.

SOURCE OF TRUTH FOR GEOMETRY: ``twin-stream-insight-main/src/three/facilityLayout.ts``.
``build_layout`` below mirrors its ``buildLayout()`` arithmetic. That mirror is
VERIFIED, not assumed: ``tests/test_facility_seed.py`` executes the real TS file
with Node and compares every rack/zone position (skipped only when Node is absent).

SCENE-UNIT SCALE (roadmap section 25, decision 5 -- owner sign-off REQUIRED):
    Verified from the TS: 3 zones x 2 rows x 6 racks = 36 racks; rack 0.6 x 2.0 x 1.0
    scene units; 0.95 along-row pitch (0.6 + 0.35 gap); row centres at z = -1.7 / +1.7
    (3.4 apart, 2.4 clear aisle); zone outlines 6.55 x 5.6. Nothing in the repo
    states what one scene unit is. PROPOSED: 1 scene unit = 1.0 m, because a
    0.6 x 2.0 x 1.0 box matches a standard 600 mm-wide, ~2 m-tall rack footprint.
    (Caveat: the 0.35 inter-rack gap and 2.4 aisle are generous for a real room.)
    That is a proposal, so the script does nothing but a DRY RUN unless you pass
    BOTH ``--scale-factor <metres per scene unit>`` and ``--confirm-scale-signoff``.
    The factor is recorded in ``facility.frame_note``.

Usage (from the repo root, DATABASE_URL set, after ``alembic upgrade head``):
    python scripts/seed_facility.py                                   # dry run: prints plan
    python scripts/seed_facility.py --scale-factor 1.0 --confirm-scale-signoff

Idempotent: refuses to touch a facility that already has assets.
No per-rack sensors are seeded: per-rack telemetry does not exist (roadmap sections 3, 10).
With ``--seed-sensors`` (T16) the five FACILITY-LEVEL anomaly-feature sensors are registered on one
facility-level asset (see ``seed_facility_sensors``). Their valid ranges are PROPOSED engineering limits,
not measured or owner-approved values.
Seeded relationships/poses start at ``--valid-from`` (default: now), because as-of
queries must not claim this layout existed before it was recorded.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_FACILITY_NAME = "Default Facility"
LAYOUT_TS = "twin-stream-insight-main/src/three/facilityLayout.ts"

# Mirrors the constants in facilityLayout.ts.
ZONE_LABELS = ("Zone A", "Zone B", "Zone C")
ROWS_PER_ZONE = 2
RACKS_PER_ROW = 6
RACK_WIDTH, RACK_HEIGHT, RACK_DEPTH = 0.6, 2.0, 1.0
RACK_GAP, ROW_GAP, ZONE_GAP = 0.35, 2.4, 3.5


@dataclass(frozen=True)
class SceneZone:
    zone_id: str
    label: str
    center_x: float
    center_z: float


@dataclass(frozen=True)
class SceneRack:
    rack_id: str
    zone_id: str
    row_id: str
    position: tuple[float, float, float]
    size: tuple[float, float, float]


def build_layout() -> tuple[list[SceneZone], list[SceneRack]]:
    """Python mirror of ``buildLayout()`` in facilityLayout.ts (scene units, Y-up)."""
    zones: list[SceneZone] = []
    racks: list[SceneRack] = []
    row_width = RACKS_PER_ROW * RACK_WIDTH + (RACKS_PER_ROW - 1) * RACK_GAP
    zone_depth = ROWS_PER_ZONE * RACK_DEPTH + (ROWS_PER_ZONE - 1) * ROW_GAP
    cursor_x = 0.0
    for zi, label in enumerate(ZONE_LABELS):
        zone_id = f"zone-{zi + 1}"
        zones.append(SceneZone(zone_id, label, cursor_x + row_width / 2, 0.0))
        for ri in range(ROWS_PER_ZONE):
            row_id = f"row-{ri + 1}"
            row_center_z = -zone_depth / 2 + RACK_DEPTH / 2 + ri * (RACK_DEPTH + ROW_GAP)
            for ki in range(RACKS_PER_ROW):
                rack_x = cursor_x + ki * (RACK_WIDTH + RACK_GAP)
                racks.append(
                    SceneRack(
                        rack_id=f"{zone_id}-{row_id}-rack-{ki + 1}",
                        zone_id=zone_id,
                        row_id=row_id,
                        position=(rack_x + RACK_WIDTH / 2, RACK_HEIGHT / 2, row_center_z),
                        size=(RACK_WIDTH, RACK_HEIGHT, RACK_DEPTH),
                    )
                )
        cursor_x += row_width + ZONE_GAP
    return zones, racks


def frame_note(scale: float) -> str:
    return (
        "Unit: metre. Right-handed frame, Y up. +X runs along rack rows, +Z runs across rows. "
        "Origin: floor level; x=0 at the -X edge of the first rack of zone-1; z=0 on the centreline "
        "between row-1 (z<0) and row-2 (z>0). Pose (x,y,z) is the centre of the asset's bounding box "
        "(zones: plan-view centre at floor level, y=0). rotation_deg is about +Y, right-hand rule, "
        "0 = default orientation. No geographic (compass) orientation is asserted. "
        f"Scene-unit -> metre factor: {scale!r} m per scene unit (owner sign-off recorded at seed time; "
        f"derived from {LAYOUT_TS}: rack 0.6 x 2.0 x 1.0 scene units, 0.95 pitch, 36 racks)."
    )


@dataclass(frozen=True)
class SeedSummary:
    facility_id: int
    zones: int
    racks: int
    scale: float
    valid_from: datetime


async def seed_default_facility(
    session,
    *,
    scale: float,
    valid_from: Optional[datetime] = None,
    facility_name: str = DEFAULT_FACILITY_NAME,
) -> SeedSummary:
    """Create zones/racks/poses/located_in edges. Caller owns the transaction (commit)."""
    from api.repositories import facility_repository as repo
    from api.repositories.facility_repository import utc

    if not (math.isfinite(scale) and scale > 0):
        raise ValueError("scale must be a positive finite number (metres per scene unit)")
    vf = utc(valid_from) if valid_from is not None else datetime.now(timezone.utc)

    facility = await repo.get_facility_by_name(session, facility_name)
    if facility is None:
        facility = await repo.insert_facility(session, name=facility_name)
    if await repo.count_assets(session, facility.id) > 0:
        raise RuntimeError(f"facility {facility.name!r} already has assets; refusing to seed twice")
    facility.frame_note = frame_note(scale)

    zones, racks = build_layout()
    zone_asset = {}
    for z in zones:
        a = await repo.insert_asset(
            session, facility_id=facility.id, asset_type="zone", external_id=z.zone_id, name=z.label
        )
        await repo.insert_pose(
            session, asset_id=a.id, x=z.center_x * scale, y=0.0, z=z.center_z * scale, rotation_deg=0.0, valid_from=vf
        )
        zone_asset[z.zone_id] = a
    for r in racks:
        a = await repo.insert_asset(
            session, facility_id=facility.id, asset_type="rack", external_id=r.rack_id, name=r.rack_id
        )
        px, py, pz = r.position
        await repo.insert_pose(
            session, asset_id=a.id, x=px * scale, y=py * scale, z=pz * scale, rotation_deg=0.0, valid_from=vf
        )
        await repo.insert_edge(
            session,
            parent_asset_id=zone_asset[r.zone_id].id,
            child_asset_id=a.id,
            relation="located_in",
            valid_from=vf,
        )
    return SeedSummary(facility.id, len(zones), len(racks), scale, vf)


# Facility-level sensors for the five anomaly features (src/anomaly_detector.py FEATURE_COLUMNS).
# (measurand == feature column name, canonical unit, proposed valid_min, proposed valid_max)
FACILITY_SENSORS: tuple[tuple[str, str, float, float], ...] = (
    ("water_flow_lpm", "L/min", 0.0, 1000.0),
    ("water_pressure_bar", "bar", 0.0, 10.0),
    ("server_outlet_temp_C", "degC", 0.0, 80.0),
    ("it_power_kw", "kW", 0.0, 2000.0),
    ("humidity_pct", "%", 0.0, 100.0),
)
FACILITY_ASSET_EXTERNAL_ID = "facility-level"
FACILITY_ASSET_TYPE = "facility"  # repo-level text; facility_service.ASSET_TYPES is outside T16's allowed files
SENSOR_SAMPLING_INTERVAL_S = 300.0  # A-1: one twin step


def facility_sensor_external_id(facility_id: int, measurand: str) -> str:
    return f"fac{facility_id}.{measurand}"


async def seed_facility_sensors(session, *, facility_name: str = DEFAULT_FACILITY_NAME) -> int:
    """Register the five facility-level anomaly-feature sensors. Idempotent; returns how many were created.

    Caller owns the transaction. Requires the facility to exist (run the layout seed first).
    """
    from sqlalchemy import select

    from api.repositories import facility_repository as repo
    from models.db_models import Asset, Sensor

    facility = await repo.get_facility_by_name(session, facility_name)
    if facility is None:
        raise RuntimeError(f"facility {facility_name!r} does not exist; seed the layout first")
    asset = (
        await session.execute(
            select(Asset).where(Asset.facility_id == facility.id, Asset.external_id == FACILITY_ASSET_EXTERNAL_ID)
        )
    ).scalar_one_or_none()
    if asset is None:
        asset = await repo.insert_asset(
            session,
            facility_id=facility.id,
            asset_type=FACILITY_ASSET_TYPE,
            external_id=FACILITY_ASSET_EXTERNAL_ID,
            name="Facility-level aggregates",
        )
    created = 0
    for measurand, unit, lo, hi in FACILITY_SENSORS:
        ext = facility_sensor_external_id(facility.id, measurand)
        exists = (await session.execute(select(Sensor.id).where(Sensor.external_id == ext))).scalar_one_or_none()
        if exists is not None:
            continue
        await repo.insert_sensor(
            session,
            asset_id=asset.id,
            measurand=measurand,
            unit=unit,
            sampling_interval_s=SENSOR_SAMPLING_INTERVAL_S,
            external_id=ext,
            min_valid=lo,
            max_valid=hi,
        )
        created += 1
    return created


def _print_plan(scale: Optional[float]) -> None:
    zones, racks = build_layout()
    xs = [r.position[0] for r in racks]
    print(f"Source: {LAYOUT_TS}")
    print(f"Plan: {len(zones)} zones, {len(racks)} racks (rack_id preserved as asset.external_id)")
    print(f"Scene extents: x {min(xs):.3f}..{max(xs):.3f}, z rows {sorted({round(r.position[2], 3) for r in racks})}")
    print("Proposed scale: 1 scene unit = 1.0 m  (NOT signed off)")
    if scale is not None:
        print(f"Requested scale: {scale} m per scene unit")


async def _run(scale: float, valid_from: Optional[datetime], seed_sensors: bool = False) -> SeedSummary:
    from database import get_session

    async with get_session() as session:  # commits on success, rolls back on error
        summary = await seed_default_facility(session, scale=scale, valid_from=valid_from)
        if seed_sensors:
            n = await seed_facility_sensors(session)
            print(f"Registered {n} facility-level anomaly-feature sensors")
        return summary


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale-factor", type=float, help="metres per scene unit (owner-approved value)")
    ap.add_argument("--confirm-scale-signoff", action="store_true", help="I confirm the owner signed off the scale")
    ap.add_argument("--valid-from", type=datetime.fromisoformat, help="ISO-8601 start of validity (default: now)")
    ap.add_argument(
        "--seed-sensors", action="store_true", help="also register the 5 facility-level anomaly sensors (T16)"
    )
    args = ap.parse_args(argv)

    _print_plan(args.scale_factor)
    if args.scale_factor is None or not args.confirm_scale_signoff:
        print("\nDRY RUN: nothing written. Pass --scale-factor and --confirm-scale-signoff to apply.")
        return 0
    summary = asyncio.run(_run(args.scale_factor, args.valid_from, args.seed_sensors))
    print(
        f"\nSeeded facility {summary.facility_id}: {summary.zones} zones, {summary.racks} racks, "
        f"scale {summary.scale} m/unit, valid_from {summary.valid_from.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
