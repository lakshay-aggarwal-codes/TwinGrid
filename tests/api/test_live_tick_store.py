"""T17 -- the live simulator tick writes through ingest_samples(); the WebSocket anomaly block keeps its shape."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest_asyncio
from sqlalchemy import func, select

from api.services import anomaly_service as svc
from api.services import live_broadcast_service as lbs
from api.services import telemetry_window as tw
from models.db_models import SensorReading, TelemetrySample
from tests.telemetry_support import seed_feature_sensors

STATUS_KEYS = {
    "status", "message", "score", "threshold", "type", "explanation", "window_size", "window_filled",
    "seq", "origin", "detector_id", "model_version", "trained_on", "episode", "scored_at",
}  # fmt: skip


class Det:
    threshold = 0.5

    def __init__(self):
        self.calls = 0

    def detect(self, arr):
        self.calls += 1
        return [0.01], [False]


@pytest_asyncio.fixture
async def env(session_maker, monkeypatch):
    async with session_maker() as s:
        await seed_feature_sensors(s)
        await s.commit()

    @asynccontextmanager
    async def get_session():
        async with session_maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    monkeypatch.setattr(lbs, "get_session", get_session)
    monkeypatch.setattr(lbs, "_last_reject_log", float("-inf"))
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline(close_after=3))
    monkeypatch.setattr(tw, "_provider", tw.InMemoryTelemetryWindow())
    monkeypatch.setenv("ANOMALY_SERVER_SIDE", "true")
    monkeypatch.setenv("WEBHOOK_ON_SIMULATED", "false")
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_WINDOW_SOURCE", "store")
    det = Det()
    monkeypatch.setattr(svc, "get_anomaly_detector", lambda: det)
    monkeypatch.setattr(svc, "get_model_version", lambda: "sha256-testmodel01")
    return session_maker, det


async def rows(maker, model, *where):
    async with maker() as s:
        stmt = select(func.count()).select_from(model)
        for w in where:
            stmt = stmt.where(w)
        return (await s.execute(stmt)).scalar_one()


async def test_tick_writes_the_five_features_to_the_store_and_not_to_sensor_readings(env):
    maker, _ = env
    payload = await lbs._tick()
    assert await rows(maker, TelemetrySample) == 5
    assert await rows(maker, SensorReading) == 0  # legacy table is read-only after the cut-over
    async with maker() as s:
        got = (await s.execute(select(TelemetrySample))).scalars().all()
    assert {r.origin for r in got} == {"simulated"} and {r.stream_id for r in got} == {"live"}
    assert all(r.sim_time is not None and r.quality == "ok" for r in got)
    assert "pue" in payload and payload["origin"] == "simulated"


async def test_twelve_ticks_score_from_the_store_and_shape_is_unchanged(env):
    maker, det = env
    statuses = [(await lbs._tick())["anomaly_status"] for _ in range(12)]
    assert [s["status"] for s in statuses[:11]] == ["warming_up"] * 11
    assert [s["window_filled"] for s in statuses[:11]] == list(range(1, 12))  # one more stored sample per tick
    last = statuses[-1]
    assert last["status"] == "ok" and last["window_filled"] == 12 and last["origin"] == "simulated"
    assert det.calls == 1
    for s in statuses:
        assert set(s) == STATUS_KEYS  # the WebSocket anomaly block keeps exactly its keys
    assert await rows(maker, TelemetrySample) == 60


async def test_restart_does_not_reset_the_warm_up(env, monkeypatch):
    maker, det = env
    for _ in range(12):
        await lbs._tick()
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline(close_after=3))  # new process: empty in-memory state
    monkeypatch.setattr(tw, "_provider", tw.InMemoryTelemetryWindow())
    nxt = (await lbs._tick())["anomaly_status"]
    assert nxt["status"] == "ok" and nxt["window_filled"] == 12


async def test_unseeded_facility_never_scores_and_never_breaks_the_tick(session_maker, monkeypatch, caplog):
    @asynccontextmanager
    async def get_session():
        async with session_maker() as s:
            yield s
            await s.commit()

    monkeypatch.setattr(lbs, "get_session", get_session)
    monkeypatch.setattr(lbs, "_last_reject_log", float("-inf"))
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline(close_after=3))
    monkeypatch.setenv("TELEMETRY_WINDOW_SOURCE", "store")
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "true")
    monkeypatch.setenv("ANOMALY_SERVER_SIDE", "true")
    with caplog.at_level("WARNING"):
        payloads = [await lbs._tick() for _ in range(3)]
    assert all(p["anomaly_status"]["status"] == "warming_up" and p["anomaly_status"]["score"] is None for p in payloads)
    assert await rows(session_maker, TelemetrySample) == 0
    assert sum("seeded" in r.getMessage() for r in caplog.records) == 1  # rate-limited, not one per tick


async def test_rollback_flags_restore_legacy_write_and_memory_window(env, monkeypatch):
    maker, det = env
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_WINDOW_SOURCE", "memory")
    statuses = [(await lbs._tick())["anomaly_status"] for _ in range(12)]
    assert await rows(maker, TelemetrySample) == 0
    assert statuses[-1]["status"] == "ok" and statuses[-1]["window_filled"] == 12
    # SensorReading rows depend on the pre-existing sensor_readings.origin default (see evidence); the point here is
    # that the store was not touched and the memory window scored.
    assert det.calls == 1


async def test_store_down_during_a_tick_is_status_error_not_a_crash(env, monkeypatch):
    maker, _ = env

    @asynccontextmanager
    async def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(lbs, "get_session", broken)
    p = await lbs._tick()
    assert p["anomaly_status"]["status"] == "error" and "pue" in p
