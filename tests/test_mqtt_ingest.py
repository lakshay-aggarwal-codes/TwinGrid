"""T17 -- MQTT and mock producers write through ingest_samples(); the consumer queue is bounded and counted."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")

from api.middleware import metrics  # noqa: E402
from models.db_models import Base, SensorReading, TelemetrySample  # noqa: E402
from src import sensor_ingestion as si  # noqa: E402
from src.telemetry.ingest import ingest_samples  # noqa: E402
from src.timeutil import utc_now  # noqa: E402
from tests.telemetry_support import factory_for, seed_feature_sensors  # noqa: E402


def dropped(reason: str) -> float:
    return si.MQTT_DROPPED_TOTAL.labels(reason=reason)._value.get()


def payload(ts=None, **over):
    p = si.generate_synthetic_payload()
    p["timestamp"] = (ts or utc_now()).isoformat()
    p["wue"] = (
        1.0  # the synthetic generator can exceed the validator's own wue range (pre-existing); keep tests deterministic
    )
    p.update(over)
    return p


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
def _env(monkeypatch):
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")


async def count(maker, model=TelemetrySample) -> int:
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


# --------------------------------------------------------------------------- end to end with a fake broker


async def test_fake_mqtt_end_to_end_stores_five_measured_samples_per_message(maker):
    queue = si.DropOldestQueue(100)
    raw = [json.dumps(payload(ts=utc_now() - timedelta(seconds=10 * i))).encode() for i in range(5)]
    for r in raw:  # what the paho on_message callback does, minus the thread hop
        queue.offer(si.parse_message(r))
    # The consumer's real write path, plus a signal that is set only AFTER the transaction has committed. (Polling
    # the row count instead would race: on the shared in-memory SQLite connection it sees uncommitted rows.)
    written = asyncio.Event()
    stored = 0

    async def real_ingest(chunk):
        nonlocal stored
        async with maker() as session:
            await ingest_samples(session, chunk, stream_id="live", origin="measured")
            await session.commit()
        stored += len(chunk)
        if stored >= 25:
            written.set()

    consumer = asyncio.create_task(si.consume_mqtt_queue(queue, ingest=real_ingest))
    await asyncio.wait_for(written.wait(), timeout=10)
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)

    async with maker() as s:
        rows = (await s.execute(select(TelemetrySample))).scalars().all()
    assert len(rows) == 25  # 5 messages x 5 anomaly features
    assert {r.origin for r in rows} == {"measured"} and {r.stream_id for r in rows} == {"live"}
    assert {r.quality for r in rows} == {"ok"} and all(r.sim_time is None for r in rows)
    assert await count(maker, SensorReading) == 0  # the legacy table is not written once the store is on


async def test_mock_producer_writes_simulated_origin_with_sim_time(maker):
    n = await si.ingest_payloads([payload()], origin="simulated", session_factory=factory_for(maker))
    assert n == 1
    async with maker() as s:
        rows = (await s.execute(select(TelemetrySample))).scalars().all()
    assert len(rows) == 5 and {r.origin for r in rows} == {"simulated"} and all(r.sim_time is not None for r in rows)


async def test_a_replayed_message_is_deduplicated_not_double_stored(maker):
    p = payload()
    await si.ingest_payloads([p], origin="measured", session_factory=factory_for(maker))
    await si.ingest_payloads([p], origin="measured", session_factory=factory_for(maker))
    assert await count(maker) == 5


async def test_all_producers_share_one_path_with_the_live_simulator(maker):
    # The only writer of telemetry_sample is src/telemetry/ingest.py; sensor_ingestion goes through it.
    import inspect

    src = inspect.getsource(si)
    assert "ingest_samples" in src and "TelemetrySample(" not in src


async def test_rollback_flag_restores_the_legacy_write(maker, monkeypatch):
    monkeypatch.setenv("TELEMETRY_STORE_ENABLED", "false")
    stored = []

    async def fake_store(state, source="mqtt"):
        stored.append(source)

    monkeypatch.setattr(si, "store_reading", fake_store)
    assert await si.ingest_payloads([payload()], origin="measured") == 1
    assert stored == ["mqtt"] and await count(maker) == 0


# --------------------------------------------------------------------------- malformed / invalid


def test_malformed_messages_are_counted():
    before = dropped(si.DROP_MALFORMED)
    for bad in (b"not json", b"\xff\xfe", b"[1, 2]", b'"text"', b"42"):
        assert si.parse_message(bad) is None
    assert dropped(si.DROP_MALFORMED) - before == 5


async def test_payload_that_fails_validation_is_counted_and_not_stored(maker):
    before = dropped(si.DROP_MALFORMED)
    n = await si.ingest_payloads(
        [payload(it_power_kw=99999.0), payload(timestamp="2026-03-01T12:00:00"), {"timestamp": "x"}],
        origin="measured",
        session_factory=factory_for(maker),
    )
    assert n == 0 and dropped(si.DROP_MALFORMED) - before == 3 and await count(maker) == 0


async def test_database_failure_is_counted_and_does_not_kill_the_consumer(maker):
    before = dropped(si.DROP_STORE_ERROR)

    def broken():
        raise RuntimeError("db down")

    assert await si.ingest_payloads([payload()], origin="measured", session_factory=broken) == 0
    assert dropped(si.DROP_STORE_ERROR) - before == 1


# --------------------------------------------------------------------------- bounded queue and burst


def test_queue_overflow_drops_the_oldest_and_counts():
    q = si.DropOldestQueue(3)
    before = dropped(si.DROP_OVERFLOW)
    for i in range(5):
        q.offer({"n": i})
    assert q.qsize() == 3 and dropped(si.DROP_OVERFLOW) - before == 2
    assert [q.get_nowait()["n"] for _ in range(3)] == [2, 3, 4]  # the freshest survive


def test_queue_bound_comes_from_config(monkeypatch):
    from api import config

    assert config.mqtt_queue_max() == 10_000
    monkeypatch.setenv("MQTT_QUEUE_MAX", "250")
    assert config.mqtt_queue_max() == 250
    monkeypatch.setenv("MQTT_QUEUE_MAX", "0")
    assert config.mqtt_queue_max() == 10_000  # malformed -> strict default, never "unbounded"
    with pytest.raises(ValueError):
        si.DropOldestQueue(0)


async def test_burst_of_20000_messages_stays_bounded_and_counters_equal_the_burst():
    burst, bound = 20_000, 10_000
    q = si.DropOldestQueue(bound)
    ok0, bad0, over0 = (dropped(r) for r in (si.DROP_OVERFLOW, si.DROP_MALFORMED, si.DROP_OVERFLOW))
    bad_every, bad_total, offered = 10, 0, 0
    peak = 0
    for i in range(burst):
        raw = b"{broken" if i % bad_every == 0 else json.dumps({"n": i}).encode()
        parsed = si.parse_message(raw)
        if parsed is None:
            bad_total += 1
            continue
        q.offer(parsed)
        offered += 1
        peak = max(peak, q.qsize())
    malformed = dropped(si.DROP_MALFORMED) - bad0
    overflow = dropped(si.DROP_OVERFLOW) - over0
    assert peak <= bound and q.qsize() == bound  # memory never grows past the bound
    assert malformed == bad_total == burst // bad_every
    assert overflow == offered - bound
    # every message of the burst is accounted for exactly once: queued + overflow-dropped + malformed
    assert q.qsize() + overflow + malformed == burst
    # the survivors are the NEWEST valid messages, in order
    valid = [i for i in range(burst) if i % bad_every != 0]
    assert q.get_nowait()["n"] == valid[-bound]
    print(f"BURST bound={bound} sent={burst} queued={bound} overflow={overflow} malformed={malformed}")


def test_dropped_total_is_exposed_on_metrics_with_all_reasons():
    body = metrics.render_metrics()[0].decode()
    for reason in si.DROP_REASONS:
        assert f'mqtt_dropped_total{{reason="{reason}"}}' in body


# --------------------------------------------------------------------------- credentials / TLS


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, *a, **k):
        self.calls: list[tuple] = []
        FakeClient.instances.append(self)

    def username_pw_set(self, user, password=None):
        self.calls.append(("auth", user, password))

    def tls_set(self, *a, **k):
        self.calls.append(("tls",))

    def connect(self, *a, **k):
        raise KeyboardInterrupt  # stop after configuration; the loop would otherwise retry forever

    def subscribe(self, *a, **k): ...
    def loop_forever(self): ...

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def _fake_paho(monkeypatch):
    mod = types.ModuleType("paho.mqtt.client")
    mod.Client = FakeClient
    mod.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
    pkg = types.ModuleType("paho")
    sub = types.ModuleType("paho.mqtt")
    monkeypatch.setitem(sys.modules, "paho", pkg)
    monkeypatch.setitem(sys.modules, "paho.mqtt", sub)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", mod)
    FakeClient.instances.clear()


def _run_thread():
    with pytest.raises(KeyboardInterrupt):
        si._mqtt_thread(lambda p: None, asyncio.new_event_loop())
    return FakeClient.instances[-1]


def test_client_uses_credentials_and_tls_when_configured(monkeypatch):
    _fake_paho(monkeypatch)
    monkeypatch.setenv("MQTT_USERNAME", "ingest")
    monkeypatch.setenv("MQTT_PASSWORD", "s3cret-pass")
    monkeypatch.setenv("MQTT_TLS", "true")
    assert _run_thread().calls == [("auth", "ingest", "s3cret-pass"), ("tls",)]


def test_client_password_can_come_from_a_file(monkeypatch, tmp_path):
    _fake_paho(monkeypatch)
    f = tmp_path / "pw"
    f.write_text("file-pass\n", encoding="utf-8")
    monkeypatch.setenv("MQTT_USERNAME", "ingest")
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)
    monkeypatch.setenv("MQTT_PASSWORD_FILE", str(f))
    monkeypatch.setenv("MQTT_TLS", "false")
    assert _run_thread().calls == [("auth", "ingest", "file-pass")]


def test_client_without_credentials_or_tls_makes_no_auth_calls_in_development(monkeypatch):
    _fake_paho(monkeypatch)
    for n in ("MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_PASSWORD_FILE", "MQTT_TLS"):
        monkeypatch.delenv(n, raising=False)
    assert _run_thread().calls == []


async def test_production_consumer_refuses_to_start_without_credentials(monkeypatch):
    from api.startup_checks import StartupConfigError

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(si, "MOCK_SENSORS", False)
    monkeypatch.setattr(si, "MQTT_BROKER", "localhost")  # the default broker name still needs credentials
    for n in ("MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_PASSWORD_FILE"):
        monkeypatch.delenv(n, raising=False)
    with pytest.raises(StartupConfigError) as info:
        await si.main_async()
    assert info.value.variables == ["MQTT_PASSWORD", "MQTT_USERNAME"]
    monkeypatch.setenv("MQTT_USERNAME", "u-SECRETUSER")
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)
    with pytest.raises(StartupConfigError) as info:
        await si.main_async()
    assert "SECRETUSER" not in str(info.value)
