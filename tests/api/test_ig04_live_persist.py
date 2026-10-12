"""IG-04 -- the live tick survives and counts persistence failures; retention can never raise into the loop."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest_asyncio
from sqlalchemy import select

from api.middleware import metrics
from api.services import anomaly_service as svc
from api.services import live_broadcast_service as lbs
from api.services import telemetry_window as tw
from models.db_models import TelemetrySample
from src.telemetry import retention
from tests.telemetry_support import seed_feature_sensors


class Det:
    threshold = 0.5

    def detect(self, arr):
        return [0.01], [False]


def _failures() -> float:
    return metrics.registry.get_sample_value("telemetry_persist_failures_total") or 0.0


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
    monkeypatch.setattr(svc, "get_anomaly_detector", lambda: Det())
    monkeypatch.setattr(svc, "get_model_version", lambda: "sha256-testmodel01")
    return session_maker


async def test_a_good_tick_does_not_count_a_failure_and_stores_simulated_rows(env):
    before = _failures()
    await lbs._tick()
    assert _failures() == before
    async with env() as s:
        origins = set((await s.execute(select(TelemetrySample.origin))).scalars().all())
    assert origins == {"simulated"}  # never 'measured'


async def test_store_failure_is_counted_and_the_tick_still_broadcasts(env, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("secret-value-123 db down")

    monkeypatch.setattr(lbs, "_store_live_sample", boom)
    before = _failures()
    payload = await lbs._tick()
    assert "pue" in payload and payload["origin"] == "simulated"
    assert _failures() - before == 1  # store failed; the legacy fallback write succeeded


async def test_store_and_fallback_both_failing_counts_twice_and_never_raises(env, monkeypatch, caplog):
    @asynccontextmanager
    async def broken():
        raise RuntimeError("secret-value-123 db down")
        yield  # pragma: no cover

    monkeypatch.setattr(lbs, "get_session", broken)
    before = _failures()
    with caplog.at_level("ERROR"):
        payload = await lbs._tick()
    assert "pue" in payload
    assert _failures() - before == 2
    persist_logs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Could not")]
    assert len(persist_logs) == 2 and all("secret-value-123" not in m for m in persist_logs)  # type only, no message


async def test_retention_failure_never_reaches_the_loop(env, monkeypatch):
    calls = []

    async def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("retention db error")

    monkeypatch.setattr(retention, "purge_expired", boom)
    monkeypatch.setattr(lbs, "_retention_last_run", float("-inf"))
    monkeypatch.setattr(lbs, "_retention_task", None)
    await lbs.broadcast_once()  # no clients: only the retention hook runs; must return normally
    task = lbs._retention_task
    assert task is not None
    await task  # the task itself swallowed the error
    assert calls == [1]
    assert (await lbs._tick())["origin"] == "simulated"  # the live tick is unaffected


async def test_retention_runs_at_most_once_per_interval(env, monkeypatch):
    calls = []

    async def fake(*a, **k):
        calls.append(1)

    monkeypatch.setattr(retention, "purge_expired", fake)
    monkeypatch.setenv("TELEMETRY_RETENTION_INTERVAL_S", "3600")
    monkeypatch.setattr(lbs, "_retention_last_run", float("-inf"))
    monkeypatch.setattr(lbs, "_retention_task", None)
    lbs.maybe_schedule_retention()
    await lbs._retention_task
    lbs.maybe_schedule_retention()  # not due yet
    await asyncio.sleep(0)
    assert calls == [1]


async def test_retention_is_off_when_the_store_is_disabled(env, monkeypatch):
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "false")
    monkeypatch.setattr(lbs, "_retention_last_run", float("-inf"))
    monkeypatch.setattr(lbs, "_retention_task", None)
    lbs.maybe_schedule_retention()
    assert lbs._retention_task is None


async def test_scheduling_outside_an_event_loop_does_not_raise(monkeypatch):
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "true")
    monkeypatch.setattr(lbs, "_retention_last_run", float("-inf"))
    monkeypatch.setattr(lbs, "_retention_task", None)
    # a synchronous caller: create_task has no running loop; the hook must swallow that
    await asyncio.get_running_loop().run_in_executor(None, lbs.maybe_schedule_retention)
    assert lbs._retention_task is None
