#!/usr/bin/env python3
"""Demo seed (Task 5): make every page show meaningful, clearly-simulated data on first launch.

Refuses to run unless ``DEMO_MODE=true``. Idempotent: running it again changes nothing.

What it creates (all labelled ``origin='simulated'``; nothing here is measured):
  * the default facility (3 zones, 36 racks) and the five facility-level anomaly-feature sensors;
  * three accounts -- viewer, operator, admin -- with passwords generated at seed time, printed ONCE to the
    console and stored nowhere else (no file, no log line, no database column other than the bcrypt hash);
  * 24 h of simulated telemetry (5-minute steps) through ``src.telemetry.ingest.ingest_samples``;
  * a few simulation runs (``SimulationRun`` + hourly ``SensorReading`` rows, the same rows
    ``/api/simulate/{hours}?persist=true`` writes, ADR 007);
  * a few anomaly alerts through the canonical alert writer ``data_repository.save_alert`` (ADR 006).

Usage (repo root, DATABASE_URL set, after ``alembic upgrade head``):
    DEMO_MODE=true python scripts/demo_seed.py

Notes
  * The telemetry values are a deterministic synthetic daily pattern (fixed formulas, no randomness), NOT the
    output of the plant model and NOT calibrated to any facility. ``sim_time`` equals ``ts_event``.
  * They go into the ``live`` stream because that is the stream the history pages and endpoints read by default.
    Their timestamps sit on a 5-minute grid in the past; the running live feed stamps its own rows with
    wall-clock tick instants, so the two never collide, and the newest live rows win the anomaly window.
  * The facility layout scale (1 scene unit = 1.0 m) is a PROPOSED value that has not been signed off by the
    owner; the seeded ``facility.frame_note`` says so.
  * ``admin`` gates the admin console (``/api/admin/*``), optimizer-proposal decisions and role changes. Admin also
    passes every operator check (``User.can_operate``: operator or admin), so the admin demo account can use all controls.
"""

from __future__ import annotations

import asyncio
import math
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ is not a package: import siblings by name

DEMO_STEP_S = 300  # one twin step (A-1)
DEMO_HOURS = 24
DEMO_USERS: tuple[tuple[str, str], ...] = (
    ("demo_viewer", "viewer"),
    ("demo_operator", "operator"),
    ("demo_admin", "admin"),
)
# (hours, mean utilisation, mean outside temp C, water stress): a handful of simulation runs.
DEMO_RUNS: tuple[tuple[int, float, float, float], ...] = (
    (24, 0.45, 18.0, 0.2),
    (24, 0.70, 28.0, 0.4),
    (24, 0.85, 36.0, 0.7),
)
# (dedupe_key suffix, severity, score, type, message). Alert rows are stamped by the database clock.
DEMO_ALERTS: tuple[tuple[str, int, str, float, str, str], ...] = (
    (
        "outlet-temp-1",
        "WARNING",
        0.62,
        "anomaly",
        "Demo: server outlet temperature drifted above its recent range (simulated).",
    ),
    ("flow-1", "WARNING", 0.58, "anomaly", "Demo: cooling water flow dipped below its recent range (simulated)."),
    ("it-power-1", "CRITICAL", 0.91, "anomaly", "Demo: IT power spike far outside its recent range (simulated)."),
)


class DemoModeRequired(RuntimeError):
    """``DEMO_MODE`` is not ``true``: the seed refuses to touch the database."""


def demo_mode_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    value = (env if env is not None else os.environ).get("DEMO_MODE", "")
    return value.strip().lower() == "true"


def require_demo_mode(env: Optional[Mapping[str, str]] = None) -> None:
    if not demo_mode_enabled(env):
        raise DemoModeRequired("refusing to seed: set DEMO_MODE=true to confirm this is a demo database")


def generate_password() -> str:
    """URL-safe, 20 characters (~120 bits). Never logged by this module."""
    return secrets.token_urlsafe(15)


def telemetry_value(feature: str, ts: datetime) -> float:
    """Deterministic synthetic daily pattern for one of the five anomaly features. No randomness, no model."""
    hour = ts.hour + ts.minute / 60.0
    day = math.sin((hour - 6.0) * math.pi / 12.0)  # peaks midday, same phase the twin's own diurnal curve uses
    wobble = math.sin(ts.minute * 0.7 + ts.hour * 1.3)
    if feature == "it_power_kw":
        return round(300.0 + 80.0 * day + 4.0 * wobble, 3)
    if feature == "server_outlet_temp_C":
        return round(30.0 + 4.0 * day + 0.4 * wobble, 3)
    if feature == "water_flow_lpm":
        return round(50.0 + 8.0 * day + 0.8 * wobble, 3)
    if feature == "water_pressure_bar":
        return round(3.0 + 0.2 * day + 0.03 * wobble, 4)
    if feature == "humidity_pct":
        return round(50.0 - 6.0 * day + 0.6 * wobble, 3)
    raise KeyError(feature)


def window_end(now: datetime) -> datetime:
    """The last whole 5-minute step at or before ``now`` (UTC)."""
    now = now.astimezone(timezone.utc)
    return now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)


def build_samples(
    sensor_ids: Mapping[str, str], end: datetime, units: Optional[Mapping[str, str]] = None
) -> list[dict[str, Any]]:
    """24 h of samples ending at ``end`` (inclusive) for every ``feature -> sensor external_id``."""
    steps = DEMO_HOURS * 3600 // DEMO_STEP_S
    samples: list[dict[str, Any]] = []
    for i in range(steps):
        ts = end - timedelta(seconds=DEMO_STEP_S * (steps - 1 - i))
        for feature, external_id in sensor_ids.items():
            sample = {"external_id": external_id, "ts_event": ts, "value": telemetry_value(feature, ts), "sim_time": ts}
            if units and feature in units:
                sample["unit"] = units[feature]
            samples.append(sample)
    return samples


@dataclass
class DemoSeedResult:
    facility_id: Optional[int] = None
    users_created: list[str] = field(default_factory=list)
    passwords: dict[str, str] = field(default_factory=dict)  # only for accounts created in THIS run
    telemetry_stored: int = 0
    runs_created: int = 0
    alerts_created: int = 0


async def seed_users(session, result: DemoSeedResult) -> None:
    from api.auth import get_user_by_username, hash_password
    from models.db_models import User

    for username, role in DEMO_USERS:
        if await get_user_by_username(session, username) is not None:
            continue  # idempotent: an existing account keeps its password, which this script cannot know
        password = generate_password()
        session.add(User(username=username, hashed_password=hash_password(password), role=role))
        result.users_created.append(username)
        result.passwords[username] = password
    await session.flush()


async def seed_layout(session, result: DemoSeedResult, valid_from: datetime) -> None:
    from seed_facility import DEFAULT_FACILITY_NAME, seed_default_facility, seed_facility_sensors

    from api.repositories import facility_repository as repo

    facility = await repo.get_facility_by_name(session, DEFAULT_FACILITY_NAME)
    if facility is None or await repo.count_assets(session, facility.id) == 0:
        summary = await seed_default_facility(session, scale=1.0, valid_from=valid_from)
        facility = await repo.get_facility_by_name(session, DEFAULT_FACILITY_NAME)
        assert facility is not None
        facility.frame_note = (facility.frame_note or "") + (
            " DEMO SEED: the 1.0 m per scene unit scale is a PROPOSED value; the owner has NOT signed it off."
        )
        result.facility_id = summary.facility_id
    else:
        result.facility_id = facility.id
    await seed_facility_sensors(session)  # idempotent


async def seed_telemetry(session, result: DemoSeedResult, now: datetime) -> None:
    from seed_facility import FACILITY_SENSORS, facility_sensor_external_id

    from api.services.telemetry_window import LIVE_STREAM
    from src.telemetry.ingest import MAX_BATCH, ingest_samples

    assert result.facility_id is not None
    ids = {m: facility_sensor_external_id(result.facility_id, m) for m, *_ in FACILITY_SENSORS}
    samples = build_samples(ids, window_end(now), {m: unit for m, unit, *_ in FACILITY_SENSORS})
    stored = 0
    for i in range(0, len(samples), MAX_BATCH):
        res = await ingest_samples(
            session, samples[i : i + MAX_BATCH], stream_id=LIVE_STREAM, origin="simulated", now=now
        )
        stored += res.stored
    # Re-running with the same clock stores nothing new: the unique key (sensor, stream, ts_event) turns a replay
    # into ``duplicate``. A later re-run only adds the steps since the previous run (values are deterministic).
    result.telemetry_stored = stored


async def seed_runs(session, result: DemoSeedResult) -> None:
    from sqlalchemy import func, select

    from api.repositories import data_repository
    from api.serialization import to_jsonable
    from api.services import twin_service
    from models.db_models import SimulationRun

    existing = int(await session.scalar(select(func.count()).select_from(SimulationRun)) or 0)
    if existing >= len(DEMO_RUNS):
        return
    for hours, util, outside, stress in DEMO_RUNS[existing:]:
        hourly = to_jsonable(twin_service.compute_simulation(hours, util, outside, stress))
        run = await data_repository.save_simulation_run(session, hours, util, stress, hourly)
        await data_repository.save_sensor_readings_bulk(session, hourly, "simulation", simulation_run_id=run.id)
        result.runs_created += 1


async def seed_alerts(session, result: DemoSeedResult) -> None:
    from api.repositories import data_repository

    for suffix, severity, score, type_, message in DEMO_ALERTS:
        key = f"demo-seed:{suffix}"
        if await data_repository.get_alert_by_dedupe_key(session, key) is not None:
            continue
        await data_repository.save_alert(
            session, score, True, type_, message, severity, dedupe_key=key, origin="simulated"
        )
        result.alerts_created += 1


async def seed_demo(session, *, now: Optional[datetime] = None) -> DemoSeedResult:
    """Seed everything. The caller owns the transaction (commit) and must have called ``require_demo_mode``."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result = DemoSeedResult()
    await seed_users(session, result)
    await seed_layout(session, result, valid_from=now)
    await seed_telemetry(session, result, now)
    await seed_runs(session, result)
    await seed_alerts(session, result)
    return result


async def _run() -> DemoSeedResult:
    from database import get_session

    async with get_session() as session:  # commits on success, rolls back on error
        return await seed_demo(session)


def format_report(result: DemoSeedResult) -> str:
    lines = [
        "Demo seed finished (all data is SIMULATED).",
        f"  facility id: {result.facility_id}",
        f"  telemetry samples stored this run: {result.telemetry_stored}",
        f"  simulation runs created: {result.runs_created}   alerts created: {result.alerts_created}",
    ]
    if result.passwords:
        lines.append("")
        lines.append("Demo accounts (shown ONCE, stored nowhere; the database keeps only a bcrypt hash):")
        for username, password in result.passwords.items():
            lines.append(f"  {username:<14} {password}")
    else:
        lines.append("  no new accounts: the demo accounts already exist (their passwords are not recoverable).")
    return "\n".join(lines)


def main() -> int:
    try:
        require_demo_mode()
    except DemoModeRequired as exc:
        print(f"demo_seed: {exc}", file=sys.stderr)
        return 2
    print(format_report(asyncio.run(_run())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
