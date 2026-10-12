"""IG-04 -- telemetry retention: deletes only expired live rows, is idempotent, is bounded, is counted."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.middleware import metrics
from api.services import telemetry_window
from models.db_models import Base, TelemetrySample
from src.telemetry import retention
from tests.telemetry_support import T0, point, put, seed_feature_sensors

DAYS = 30
RETENTION_NOW = T0 + timedelta(days=60)  # cutoff = T0 + 30 d
OLD = T0 + timedelta(days=1)  # expired
EDGE_NEW = T0 + timedelta(days=31)  # inside the window
FEATURES = telemetry_window.FEATURE_ORDER  # 5 features


@pytest_asyncio.fixture
async def maker():
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with m() as s:
        await seed_feature_sensors(s)
        await s.commit()
    yield m
    await eng.dispose()


def factory(m):
    @asynccontextmanager
    async def f():
        async with m() as s:
            yield s

    return f


async def _store(m, at, *, stream="live", origin="simulated"):
    samples = [point(f, 0, at=at, simulated=origin == "simulated") for f in FEATURES]
    async with m() as s:
        await put(s, samples, origin=origin, stream=stream, now=RETENTION_NOW)


async def _count(m, *where):
    async with m() as s:
        stmt = select(func.count()).select_from(TelemetrySample)
        for w in where:
            stmt = stmt.where(w)
        return (await s.execute(stmt)).scalar_one()


def _deleted_metric() -> float:
    return metrics.registry.get_sample_value("telemetry_retention_deleted_rows_total") or 0.0


async def test_deletes_only_expired_live_rows(maker):
    replay = "replay:" + str(uuid.uuid4())
    await _store(maker, OLD)  # live, expired
    await _store(maker, EDGE_NEW)  # live, inside the window
    await _store(maker, OLD, stream=replay, origin="replay")  # old but another stream: a deliberate dataset
    assert await _count(maker) == 15

    res = await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS)

    assert res.deleted == 5 and not res.more_remaining
    assert await _count(maker, TelemetrySample.stream_id == "live", TelemetrySample.ts_event < res.cutoff) == 0
    assert await _count(maker, TelemetrySample.stream_id == "live") == 5  # the newer live rows are intact
    assert await _count(maker, TelemetrySample.stream_id == replay) == 5  # other streams are never touched


async def test_second_run_is_a_no_op(maker):
    await _store(maker, OLD)
    first = await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS)
    before = _deleted_metric()
    second = await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS)
    assert (first.deleted, second.deleted) == (5, 0)
    assert _deleted_metric() == before


async def test_batches_are_bounded_and_the_next_run_finishes(maker):
    await _store(maker, OLD)  # 5 expired rows
    first = await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS, batch_size=2, max_batches=2)
    assert (first.deleted, first.batches, first.more_remaining) == (4, 2, True)
    second = await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS, batch_size=2, max_batches=2)
    assert (second.deleted, second.more_remaining) == (1, False)
    assert await _count(maker) == 0


async def test_deleted_rows_are_counted(maker):
    await _store(maker, OLD)
    before = _deleted_metric()
    await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS)
    assert _deleted_metric() - before == 5


async def test_dry_run_deletes_and_counts_nothing(maker):
    await _store(maker, OLD)
    before = _deleted_metric()
    res = await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS, dry_run=True)
    assert res.dry_run and res.deleted == 5
    assert await _count(maker) == 5 and _deleted_metric() == before


async def test_row_exactly_at_the_cutoff_is_kept(maker):
    await _store(maker, RETENTION_NOW - timedelta(days=DAYS))
    res = await retention.purge_expired(factory(maker), now=RETENTION_NOW, days=DAYS)
    assert res.deleted == 0 and await _count(maker) == 5


async def test_a_restart_replaying_the_same_tick_does_not_duplicate_rows(maker):
    # Idempotency key: UNIQUE (sensor_id, stream_id, ts_event) (uq_telemetry_sensor_stream_event). A tick that is
    # written twice with the same ts_event leaves one row per sensor; nothing is lost either.
    await _store(maker, EDGE_NEW)
    await _store(maker, EDGE_NEW)
    assert await _count(maker) == 5


async def test_stored_simulated_rows_are_never_origin_measured(maker):
    await _store(maker, EDGE_NEW)
    assert await _count(maker, TelemetrySample.origin == "measured") == 0
    assert await _count(maker, TelemetrySample.origin == "simulated") == 5


def test_env_defaults_and_fallbacks(monkeypatch):
    monkeypatch.delenv("TELEMETRY_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("TELEMETRY_RETENTION_INTERVAL_S", raising=False)
    assert retention.retention_days() == 30 and retention.retention_interval_s() == 3600.0
    monkeypatch.setenv("TELEMETRY_RETENTION_DAYS", "7")
    monkeypatch.setenv("TELEMETRY_RETENTION_INTERVAL_S", "60")
    assert retention.retention_days() == 7 and retention.retention_interval_s() == 60.0
    for bad in ("0", "-3", "abc", "inf", ""):
        monkeypatch.setenv("TELEMETRY_RETENTION_DAYS", bad)
        monkeypatch.setenv("TELEMETRY_RETENTION_INTERVAL_S", bad)
        assert retention.retention_days() == 30 and retention.retention_interval_s() == 3600.0


def test_live_stream_name_matches_the_telemetry_window():
    assert retention.LIVE_STREAM == telemetry_window.LIVE_STREAM


def test_invalid_arguments_are_rejected():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(retention.purge_expired(lambda: None, batch_size=0))
    with pytest.raises(ValueError):
        asyncio.run(retention.purge_expired(lambda: None, days=0))
