"""Shared helpers for the T17 tests: five facility-level feature sensors and a way to put samples in the store."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from api import config
from api.repositories import facility_repository as repo
from api.services.telemetry_window import FEATURE_ORDER
from src.telemetry.ingest import ingest_samples

UTC = timezone.utc
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
STEP = timedelta(seconds=300)
NOW = T0 + timedelta(days=2)  # "now" for ingest: every test timestamp is in the past
UNITS = {
    "water_flow_lpm": "L/min",
    "water_pressure_bar": "bar",
    "server_outlet_temp_C": "degC",
    "it_power_kw": "kW",
    "humidity_pct": "%",
}
VALUES = {
    "water_flow_lpm": 50.0,
    "water_pressure_bar": 3.0,
    "server_outlet_temp_C": 30.0,
    "it_power_kw": 300.0,
    "humidity_pct": 50.0,
}


def ext(feature: str) -> str:
    return config.telemetry_feature_sensors()[feature]


async def seed_feature_sensors(session, *, interval_s: float = 300.0, overrides: dict[str, float] | None = None):
    """Register the five feature sensors under the default mapping (``fac<id>.<feature>``). Returns the facility."""
    fac = await repo.insert_facility(session, name="t17-facility")
    asset = await repo.insert_asset(
        session, facility_id=fac.id, asset_type="facility", external_id="facility-level", name="agg"
    )
    for feature in FEATURE_ORDER:
        await repo.insert_sensor(
            session,
            asset_id=asset.id,
            measurand=feature,
            unit=UNITS[feature],
            sampling_interval_s=(overrides or {}).get(feature, interval_s),
            external_id=f"fac{fac.id}.{feature}",
            min_valid=-1000.0,
            max_valid=100000.0,
        )
    await session.flush()
    return fac


def point(feature: str, i: int, *, value: float | None = None, simulated: bool = True, at: datetime | None = None):
    """Sample ``i`` (0-based, 300 s apart) of ``feature``."""
    ts = at if at is not None else T0 + i * STEP
    sample = {"external_id": ext(feature), "ts_event": ts, "value": VALUES[feature] if value is None else value}
    if simulated:
        sample["sim_time"] = ts
    return sample


async def put(session, samples, *, origin="simulated", stream="live", now=NOW):
    result = await ingest_samples(session, samples, stream_id=stream, origin=origin, now=now)
    await session.commit()
    return result


async def put_steps(session, indices, *, origin="simulated", stream="live", features=FEATURE_ORDER, **kw):
    """One sample per feature for every step index in ``indices``."""
    simulated = origin == "simulated"
    samples = [point(f, i, simulated=simulated, **kw) for i in indices for f in features]
    return await put(session, samples, origin=origin, stream=stream)


def factory_for(session_maker):
    @asynccontextmanager
    async def factory():
        async with session_maker() as s:
            yield s

    return factory
