"""T17 -- the anomaly window is built from STORED samples (roadmap 9.5)."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")

from api.services import anomaly_service as svc  # noqa: E402
from api.services import telemetry_window as tw  # noqa: E402
from models.db_models import Base  # noqa: E402
from tests.telemetry_support import (  # noqa: E402
    STEP,
    T0,
    factory_for,
    point,
    put,
    put_steps,
    seed_feature_sensors,
)

FEATURES = tw.FEATURE_ORDER


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


@pytest.fixture(autouse=True)
def _store_source(monkeypatch):
    monkeypatch.setenv("TELEMETRY_WINDOW_SOURCE", "store")
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "true")
    monkeypatch.setenv("ANOMALY_SERVER_SIDE", "true")


async def window(maker):
    async with maker() as s:
        return await tw.load_store_window(s)


# --------------------------------------------------------------------------- pure evaluator rules


async def test_twelve_contiguous_valid_single_origin_samples_are_scorable(maker):
    async with maker() as s:
        await put_steps(s, range(12))
    w = await window(maker)
    assert w.scorable and w.reason is None and w.filled == 12 and len(w.samples) == 12
    assert [x.features for x in w.samples][0] == (50.0, 3.0, 30.0, 300.0, 50.0)  # model feature order
    assert {x.origin for x in w.samples} == {"simulated"}
    assert [x.seq for x in w.samples] == sorted(x.seq for x in w.samples)


async def test_fewer_than_twelve_is_insufficient_with_fill_count(maker):
    async with maker() as s:
        await put_steps(s, range(7))
    w = await window(maker)
    assert not w.scorable and w.reason == tw.REASON_INSUFFICIENT and w.filled == 7 and w.samples == []


async def test_empty_store_is_insufficient(maker):
    w = await window(maker)
    assert w.reason == tw.REASON_INSUFFICIENT and w.filled == 0


async def test_unknown_feature_sensor_is_insufficient(maker, monkeypatch):
    monkeypatch.setenv("TELEMETRY_FACILITY_ID", "99")  # fac99.* does not exist
    async with maker() as s:
        await put_steps(s, range(12))
    assert (await window(maker)).reason == tw.REASON_INSUFFICIENT


async def test_gap_in_window_means_no_score(maker):
    async with maker() as s:
        await put_steps(s, [*range(0, 6), *range(8, 14)])  # steps 6 and 7 are missing: a 900 s hole (> 1.5 x 300)
    w = await window(maker)
    assert not w.scorable and w.reason == tw.REASON_GAP and w.samples == []


async def test_gap_in_a_single_sensor_means_no_score(maker):
    async with maker() as s:
        await put_steps(s, range(12))
        # the pressure sensor then misses step 12, the others have it: 13th reference sample has no aligned partner
        await put_steps(s, [12], features=[f for f in FEATURES if f != "water_pressure_bar"])
    w = await window(maker)
    assert not w.scorable and w.reason == tw.REASON_GAP


async def test_step_of_exactly_one_and_a_half_intervals_is_not_a_gap():
    def series(ts_list):
        from api.services.telemetry_window import SensorSeries, StoredPoint

        pts = [StoredPoint(i, t, t, 1.0, "ok", "simulated") for i, t in enumerate(ts_list)]
        return {f: SensorSeries(f, 300.0, pts) for f in FEATURES}

    times = [T0 + timedelta(seconds=300 * i) for i in range(11)] + [T0 + timedelta(seconds=300 * 10 + 450)]
    assert tw.evaluate_window(series(times), cadence_s=300).scorable  # == 1.5 x interval: allowed
    times[-1] = T0 + timedelta(seconds=300 * 10 + 451)
    assert tw.evaluate_window(series(times), cadence_s=300).reason == tw.REASON_GAP  # > 1.5 x interval


async def test_invalid_sample_inside_window_is_not_scorable(maker):
    async with maker() as s:
        await put_steps(s, range(12))
        # an out-of-range value is STORED with quality=invalid at step 12 -> in the latest-12 window
        await put(s, [point("it_power_kw", 12, value=1e9)] + [point(f, 12) for f in FEATURES if f != "it_power_kw"])
    w = await window(maker)
    assert not w.scorable and w.reason == tw.REASON_INVALID_SAMPLE and w.samples == []
    # and it is not rescued by the 11 good samples before it: the filled count is the trailing valid run, 0
    assert w.filled == 0


async def test_invalid_sample_outside_the_latest_window_does_not_matter(maker):
    async with maker() as s:
        await put(s, [point("it_power_kw", 0, value=1e9)] + [point(f, 0) for f in FEATURES if f != "it_power_kw"])
        await put_steps(s, range(1, 13))
    assert (await window(maker)).scorable


async def test_mixed_origin_is_not_scorable(maker):
    async with maker() as s:
        await put_steps(s, range(8), origin="simulated")
        await put_steps(s, range(8, 12), origin="measured")
    w = await window(maker)
    assert not w.scorable and w.reason == tw.REASON_MIXED_ORIGIN


async def test_measured_only_window_is_scorable_and_labelled_measured(maker):
    async with maker() as s:
        await put_steps(s, range(12), origin="measured")
    w = await window(maker)
    assert w.scorable and {x.origin for x in w.samples} == {"measured"}


async def test_cadence_mismatch_is_not_scorable(maker):
    async with maker() as s:
        await put_steps(s, range(12))
    async with maker() as s:
        series = await tw.load_store_series(s)
    assert tw.evaluate_window(series, cadence_s=60).reason == tw.REASON_CADENCE_MISMATCH


async def test_sensor_with_a_different_interval_is_a_cadence_mismatch():
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with m() as s:
        await seed_feature_sensors(s, overrides={"humidity_pct": 60.0})
        await s.commit()
    async with m() as s:
        await put_steps(s, range(12))
    assert (await window(m)).reason == tw.REASON_CADENCE_MISMATCH
    await eng.dispose()


async def test_replay_and_import_streams_never_feed_the_window(maker):
    replay = "replay:123e4567-e89b-12d3-a456-426614174000"
    async with maker() as s:
        await put_steps(s, range(12), origin="replay", stream=replay)
        await put_steps(s, range(12), origin="measured", stream="import:ds1")
    w = await window(maker)
    assert w.reason == tw.REASON_INSUFFICIENT and w.filled == 0


async def test_alignment_tolerance_is_half_an_interval(maker):
    async with maker() as s:
        await put_steps(s, range(11))
        # last step: the flow sensor is 149 s late (within 0.5 x 300), everything else on time
        late = [point(f, 11) for f in FEATURES if f != "water_flow_lpm"]
        late.append(point("water_flow_lpm", 11, at=T0 + 11 * STEP + timedelta(seconds=149)))
        await put(s, late)
    assert (await window(maker)).scorable
    async with maker() as s:
        await put_steps(s, [12], features=[f for f in FEATURES if f != "water_flow_lpm"])
        await put(s, [point("water_flow_lpm", 12, at=T0 + 12 * STEP + timedelta(seconds=151))])
    assert (await window(maker)).reason == tw.REASON_GAP  # 151 s > 0.5 x 300: no aligned partner


# --------------------------------------------------------------------------- idle then resume


async def test_idle_then_resume_requires_twelve_fresh_contiguous_samples(maker):
    async with maker() as s:
        await put_steps(s, range(12))
    assert (await window(maker)).scorable

    # the producer stops for an hour (12 steps), then resumes: old samples are still in the store
    resume = 24
    seen = []
    for k in range(12):
        async with maker() as s:
            await put_steps(s, [resume + k])
        w = await window(maker)
        seen.append((w.scorable, w.reason, w.filled))
    # first fresh sample after the hole: the latest 12 still include the old ones across a gap -> not scorable
    assert all(not ok for ok, _, _ in seen[:-1]), seen
    assert [r for _, r, _ in seen[:-1]] == [tw.REASON_GAP] * 11
    assert [f for _, _, f in seen[:-1]] == list(range(1, 12))  # fill counts up 1..11 on fresh samples only
    assert seen[-1] == (True, None, 12)  # the 12th fresh contiguous sample makes it scorable again


# --------------------------------------------------------------------------- restart


async def test_restart_rebuilds_the_window_from_the_store(maker, monkeypatch):
    async with maker() as s:
        await put_steps(s, range(12))
    first = await window(maker)
    assert first.scorable

    # "restart": brand-new in-memory provider and pipeline, same database
    monkeypatch.setattr(tw, "_provider", tw.InMemoryTelemetryWindow())
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline(close_after=3))
    assert len(tw.get_window_provider().window(12)) == 0  # the ring buffer is empty

    class Det:
        threshold = 0.5
        calls = 0

        def detect(self, arr):
            Det.calls += 1
            return [0.01], [False]

    monkeypatch.setattr(svc, "get_anomaly_detector", lambda: Det())
    monkeypatch.setattr(svc, "get_model_version", lambda: "sha256-testmodel01")
    result = await svc.get_pipeline().process(session_factory=factory_for(maker))
    assert (
        result["status"] == svc.STATUS_OK and Det.calls == 1
    )  # scored straight away: no 12-tick warm-up after a restart
    assert result["window_filled"] == 12 and result["origin"] == "simulated"
    again = await window(maker)
    assert [x.features for x in again.samples] == [x.features for x in first.samples]


async def test_pipeline_reports_warming_up_with_reason_and_never_scores_a_gappy_window(maker, monkeypatch):
    async with maker() as s:
        await put_steps(s, [*range(0, 6), *range(8, 14)])
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline(close_after=3))
    scored = []
    monkeypatch.setattr(svc, "score_window_features", lambda f: scored.append(f) or {})
    r = await svc.get_pipeline().process(session_factory=factory_for(maker))
    assert r["status"] == svc.STATUS_WARMING_UP and "gap" in r["message"] and r["score"] is None
    assert scored == []
    # the status object keeps exactly the keys the WebSocket consumers already read
    assert set(r) == {
        "status", "message", "score", "threshold", "type", "explanation", "window_size", "window_filled",
        "seq", "origin", "detector_id", "model_version", "trained_on", "episode", "scored_at",
    }  # fmt: skip


async def test_store_read_failure_fails_closed_not_to_the_memory_window(monkeypatch):
    # an unreadable store must surface (the live tick turns it into status=error), never silently use the ring buffer
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline(close_after=3))
    with pytest.raises(RuntimeError):
        await svc.get_pipeline().process(session_factory=broken)


async def test_memory_source_is_the_rollback(maker, monkeypatch):
    monkeypatch.setenv("TELEMETRY_WINDOW_SOURCE", "memory")
    monkeypatch.setattr(tw, "_provider", tw.InMemoryTelemetryWindow())
    assert tw.effective_window_source() == "memory"
    w = await tw.current_window(factory_for(maker))
    assert w.reason == tw.REASON_INSUFFICIENT and w.filled == 0
    for i in range(12):
        tw.get_window_provider().append(
            tw.sample_from_state(
                dict(zip(FEATURES, (1.0,) * 5)), seq=i, ts_ingest="2026-01-01T00:00:00+00:00", origin="simulated"
            )
        )
    assert (await tw.current_window(factory_for(maker))).scorable


def test_store_disabled_falls_back_to_memory_window(monkeypatch):
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "false")
    assert tw.effective_window_source() == "memory"


def test_unknown_window_source_value_does_not_select_memory(monkeypatch):
    monkeypatch.setenv("TELEMETRY_WINDOW_SOURCE", "bogus")
    assert tw.effective_window_source() == "store"
