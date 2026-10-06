"""T16 -- telemetry store and ``ingest_samples`` (roadmap §9.1, §9.3).

Every behavioural test runs on SQLite and, when ``TWINGRID_TEST_PG_ASYNC_URL`` is set
(e.g. ``postgresql+asyncpg://user@host/db``), on PostgreSQL in an isolated schema. PostgreSQL is
authoritative for ``ON CONFLICT`` concurrency and ``EXPLAIN``; SQLite is a smoke check of the same rules.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import logging
import math
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.middleware import metrics
from api.repositories import facility_repository as repo
from models.db_models import Base, Sensor, TelemetrySample
from src.telemetry import validation as v
from src.telemetry.ingest import MAX_BATCH, BatchTooLargeError, ingest_samples

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
PG_URL = os.getenv("TWINGRID_TEST_PG_ASYNC_URL")
LIVE = "live"

BACKENDS = [
    "sqlite",
    pytest.param("pg", marks=pytest.mark.skipif(not PG_URL, reason="TWINGRID_TEST_PG_ASYNC_URL not set")),
]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class Db:
    def __init__(self, engine, kind: str):
        self.engine, self.kind = engine, kind
        self.maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture(params=BACKENDS)
async def db(request):
    kind = request.param
    if kind == "sqlite":
        eng = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield Db(eng, kind)
        await eng.dispose()
    else:
        schema = "t16_" + uuid.uuid4().hex[:10]
        admin = create_async_engine(PG_URL)
        async with admin.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        eng = create_async_engine(PG_URL, connect_args={"server_settings": {"search_path": schema}})
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield Db(eng, kind)
        await eng.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


async def _seed_sensors(session: AsyncSession, **overrides) -> dict[str, Sensor]:
    fac = await repo.insert_facility(session, name=f"f-{uuid.uuid4().hex[:6]}")
    asset = await repo.insert_asset(session, facility_id=fac.id, asset_type="zone", external_id="z", name="z")
    out = {}
    for ext, unit, lo, hi in (("temp", "degC", -10.0, 100.0), ("flow", "L/min", 0.0, None), ("free", "kW", None, None)):
        out[ext] = await repo.insert_sensor(
            session, asset_id=asset.id, measurand=ext, unit=unit, sampling_interval_s=300.0,
            external_id=ext, min_valid=lo, max_valid=hi,
        )  # fmt: skip
    await session.commit()
    return out


@pytest_asyncio.fixture
async def session(db):
    async with db.maker() as s:
        await _seed_sensors(s)
        yield s


def smp(ext="temp", ts=NOW, value=20.0, **kw):
    return {"external_id": ext, "ts_event": _iso(ts) if isinstance(ts, datetime) else ts, "value": value, **kw}


async def ingest(session, samples, *, stream=LIVE, origin="measured", now=NOW, commit=True, **kw):
    res = await ingest_samples(session, samples, stream_id=stream, origin=origin, now=now, **kw)
    if commit:
        await session.commit()
    return res


async def rows(session, **where):
    stmt = select(TelemetrySample).order_by(TelemetrySample.id)
    for k, val in where.items():
        stmt = stmt.where(getattr(TelemetrySample, k) == val)
    return list((await session.execute(stmt)).scalars().all())


# --------------------------------------------------------------------------- §9.3 rules
async def test_accepted_sample_is_stored_with_contract_fields(session):
    r = await ingest(session, [smp(value=21.5)])
    assert r.counts[v.ACCEPTED] == 1 and r.stored == 1 and r.rejected == 0
    (row,) = await rows(session)
    assert (row.value, row.quality, row.invalid_reason, row.origin, row.stream_id) == (
        21.5,
        "ok",
        None,
        "measured",
        LIVE,
    )
    assert row.sim_time is None and row.batch_id == r.batch_id
    assert row.ts_event.replace(tzinfo=row.ts_event.tzinfo or UTC).astimezone(UTC) == NOW
    assert row.ts_ingest.replace(tzinfo=row.ts_ingest.tzinfo or UTC).astimezone(UTC) == NOW


async def test_identical_duplicate_is_duplicate_and_adds_no_row(session):
    await ingest(session, [smp(value=20.0)])
    r = await ingest(session, [smp(value=20.0)])
    assert r.counts[v.DUPLICATE] == 1 and r.stored == 0
    assert len(await rows(session)) == 1


async def test_same_key_different_value_is_conflict_first_kept_and_logged(session, caplog):
    first = await ingest(session, [smp(value=20.0)])
    with caplog.at_level(logging.WARNING, logger="src.telemetry.ingest"):
        second = await ingest(session, [smp(value=25.0)])
    assert second.counts[v.CONFLICT] == 1 and second.stored == 0
    (row,) = await rows(session)
    assert row.value == 20.0 and row.batch_id == first.batch_id
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert str(first.batch_id) in msg and str(second.batch_id) in msg  # both batch ids logged


async def test_duplicate_and_conflict_inside_one_batch(session):
    r = await ingest(session, [smp(value=1.0), smp(value=1.0), smp(value=2.0)])
    assert (r.counts[v.ACCEPTED], r.counts[v.DUPLICATE], r.counts[v.CONFLICT]) == (1, 1, 1)
    assert [x.outcome for x in r.results] == [v.ACCEPTED, v.DUPLICATE, v.CONFLICT]
    assert [row.value for row in await rows(session)] == [1.0]


async def test_out_of_order_and_late_samples_are_accepted(session):
    ts = [NOW - timedelta(seconds=s) for s in (0, 600, 300, 86400 * 30)]  # newest first, then late, then 30 days old
    r = await ingest(session, [smp(ts=t, value=float(i)) for i, t in enumerate(ts)])
    assert r.counts[v.ACCEPTED] == 4 and r.rejected == 0
    assert len(await rows(session)) == 4


async def test_future_beyond_5s_is_stored_invalid_future(session):
    r = await ingest(session, [smp(ts=NOW + timedelta(seconds=5, microseconds=1))])
    assert r.counts[v.INVALID_FUTURE] == 1 and r.stored == 1
    (row,) = await rows(session)
    assert (row.quality, row.invalid_reason) == ("invalid", "future")


async def test_exactly_5s_ahead_is_still_ok(session):
    r = await ingest(session, [smp(ts=NOW + timedelta(seconds=5))])
    assert r.counts[v.ACCEPTED] == 1


@pytest.mark.parametrize("ext, value", [("temp", -10.1), ("temp", 100.1), ("flow", -0.001), ("temp", 1e9)])
async def test_out_of_range_is_stored_invalid_range(session, ext, value):
    r = await ingest(session, [smp(ext, value=value)])
    assert r.counts[v.INVALID_RANGE] == 1
    (row,) = await rows(session)
    assert (row.quality, row.invalid_reason, row.value) == ("invalid", "range", value)


@pytest.mark.parametrize(
    "ext, value", [("temp", -10.0), ("temp", 100.0), ("flow", 0.0), ("flow", 1e12), ("free", -1e30)]
)
async def test_range_bounds_are_inclusive_and_none_means_unbounded(session, ext, value):
    assert (await ingest(session, [smp(ext, value=value)])).counts[v.ACCEPTED] == 1


async def test_future_takes_precedence_over_range(session):
    await ingest(session, [smp(ts=NOW + timedelta(hours=1), value=1e9)])
    (row,) = await rows(session)
    assert row.invalid_reason == "future"


async def test_invalid_rows_are_stored_but_flagged_never_ok(session):
    await ingest(session, [smp(ts=NOW, value=1e9), smp(ts=NOW + timedelta(seconds=1), value=20.0)])
    oks = await rows(session, quality="ok")
    assert [r.value for r in oks] == [20.0]


async def test_unknown_sensor_is_rejected_not_stored(session):
    r = await ingest(session, [smp("nope"), {"ts_event": _iso(NOW), "value": 1.0}, smp(ext=None)])
    assert r.counts[v.UNKNOWN_SENSOR] == 3 and r.stored == 0
    assert await rows(session) == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "20", None, True, [1.0], 10**400])
async def test_non_finite_or_non_numeric_value_is_rejected(session, bad):
    r = await ingest(session, [smp(value=bad)])
    assert r.counts[v.INVALID_VALUE] == 1 and r.stored == 0
    assert await rows(session) == []


@pytest.mark.parametrize("bad_ts", ["2026-03-01T12:00:00", "2026-03-01", "garbage", "", None, 1772366400])
async def test_naive_or_unparseable_timestamp_is_rejected_invalid_time(session, bad_ts):
    r = await ingest(session, [smp(ts=bad_ts)])
    assert r.counts[v.INVALID_TIME] == 1 and r.stored == 0
    assert await rows(session) == []


async def test_naive_timestamp_accepted_only_with_an_explicit_zone(session):
    ist = "2026-03-01T17:30:00"  # == 12:00 UTC in Asia/Kolkata
    r = await ingest(session, [smp(ts=ist, source_tz="Asia/Kolkata")])
    assert r.counts[v.ACCEPTED] == 1
    (row,) = await rows(session)
    assert row.ts_event.replace(tzinfo=row.ts_event.tzinfo or UTC).astimezone(UTC) == NOW


async def test_naive_policy_sensor_tz_reads_naive_in_the_sensors_zone(session):
    await session.execute(
        Sensor.__table__.update().where(Sensor.external_id == "temp").values(source_tz="Asia/Kolkata")
    )
    await session.commit()
    r = await ingest(session, [smp(ts="2026-03-01T17:30:00")], naive_policy="sensor_tz")
    assert r.counts[v.ACCEPTED] == 1


async def test_aware_offsets_are_normalised_to_the_same_utc_key(session):
    a = await ingest(session, [smp(ts="2026-03-01T17:30:00+05:30", value=7.0)])
    b = await ingest(session, [smp(ts="2026-03-01T12:00:00Z", value=7.0)])
    assert a.counts[v.ACCEPTED] == 1 and b.counts[v.DUPLICATE] == 1


async def test_unit_mismatch_is_rejected_without_conversion(session):
    r = await ingest(
        session, [smp(unit="degF", value=68.0), smp(ts=NOW + timedelta(seconds=1), unit="degC", value=20.0)]
    )
    assert (r.counts[v.UNIT_MISMATCH], r.counts[v.ACCEPTED]) == (1, 1)
    assert [x.value for x in await rows(session)] == [20.0]


async def test_batch_over_1000_is_rejected_whole_and_1000_is_accepted(session):
    batch = [smp(ts=NOW - timedelta(seconds=i), value=float(i % 50)) for i in range(MAX_BATCH + 1)]
    with pytest.raises(BatchTooLargeError):
        await ingest_samples(session, batch, stream_id=LIVE, origin="measured", now=NOW)
    assert await rows(session) == []
    r = await ingest(session, batch[:MAX_BATCH])
    assert r.counts[v.ACCEPTED] == MAX_BATCH
    assert (await session.execute(select(func.count()).select_from(TelemetrySample))).scalar_one() == MAX_BATCH


async def test_empty_batch_is_a_valid_noop(session):
    r = await ingest(session, [])
    assert r.stored == 0 and sum(r.counts.values()) == 0


async def test_one_batch_id_and_one_ts_ingest_per_call(session):
    r = await ingest(session, [smp(ts=NOW - timedelta(seconds=i)) for i in range(3)])
    rs = await rows(session)
    assert {x.batch_id for x in rs} == {r.batch_id} and len({x.ts_ingest for x in rs}) == 1
    r2 = await ingest(session, [smp(ts=NOW - timedelta(seconds=99))])
    assert r2.batch_id != r.batch_id


async def test_default_ts_ingest_is_the_server_clock_in_aware_utc(session):
    before = datetime.now(UTC)
    r = await ingest_samples(session, [smp(ts=before)], stream_id=LIVE, origin="measured")
    await session.commit()
    assert r.ts_ingest.tzinfo is not None and r.ts_ingest.utcoffset() == timedelta(0)
    assert before <= r.ts_ingest <= datetime.now(UTC)


async def test_missing_data_is_never_imputed(session):
    await ingest(session, [smp(ts=NOW), smp(ts=NOW + timedelta(minutes=15))])  # 15 min gap at 5 min cadence
    assert len(await rows(session)) == 2


# --------------------------------------------------------------------------- streams / origin / sim_time
async def test_streams_are_independent_and_replay_cannot_alter_live(session):
    rid = f"replay:{uuid.uuid4()}"
    await ingest(session, [smp(value=1.0)])
    r = await ingest(session, [smp(value=99.0)], stream=rid, origin="replay")
    assert r.counts[v.ACCEPTED] == 1  # same sensor + ts_event, different stream: not a conflict
    assert [x.value for x in await rows(session, stream_id=LIVE)] == [1.0]
    assert [x.value for x in await rows(session, stream_id=rid)] == [99.0]
    r = await ingest(session, [smp(value=2.0)], stream="import:ds-1", origin="replay")
    assert r.counts[v.ACCEPTED] == 1


@pytest.mark.parametrize("bad", ["", "LIVE", "replay:abc", "import:", "import:a b", "x" * 65, None, "live "])
async def test_bad_stream_id_is_rejected(session, bad):
    with pytest.raises(ValueError):
        await ingest_samples(session, [smp()], stream_id=bad, origin="measured", now=NOW)


@pytest.mark.parametrize("bad", [None, "", "real", "MEASURED"])
async def test_origin_is_required_and_validated(session, bad):
    with pytest.raises(ValueError):
        await ingest_samples(session, [smp()], stream_id=LIVE, origin=bad, now=NOW)
    with pytest.raises(TypeError):  # keyword-only, no default
        await ingest_samples(session, [smp()], stream_id=LIVE, now=NOW)  # type: ignore[call-arg]


async def test_simulated_requires_sim_time_and_stores_it(session):
    sim = NOW - timedelta(days=3)
    r = await ingest(session, [smp(ts=NOW, sim_time=_iso(sim))], origin="simulated")
    assert r.counts[v.ACCEPTED] == 1
    (row,) = await rows(session)
    assert row.origin == "simulated" and row.sim_time.replace(tzinfo=row.sim_time.tzinfo or UTC).astimezone(UTC) == sim
    r = await ingest(session, [smp(ts=NOW + timedelta(seconds=1))], origin="simulated")
    assert r.counts[v.INVALID_TIME] == 1  # simulated without sim_time
    r = await ingest(session, [smp(ts=NOW + timedelta(seconds=2), sim_time="2026-01-01T00:00:00")], origin="simulated")
    assert r.counts[v.INVALID_TIME] == 1  # naive sim_time


async def test_sim_time_is_rejected_for_non_simulated_origin(session):
    r = await ingest(session, [smp(sim_time=_iso(NOW))], origin="measured")
    assert r.counts[v.INVALID_TIME] == 1 and await rows(session) == []


# --------------------------------------------------------------------------- schema constraints
async def test_db_constraints_reject_bad_rows_even_if_the_writer_is_bypassed(session):
    sid = (await session.execute(select(Sensor.id).where(Sensor.external_id == "temp"))).scalar_one()
    base = dict(
        sensor_id=sid, stream_id=LIVE, ts_event=NOW, ts_ingest=NOW, value=1.0, quality="ok", batch_id=uuid.uuid4()
    )
    for bad in (
        dict(origin="measured", sim_time=NOW),  # sim_time only when simulated
        dict(origin="simulated"),  # simulated needs sim_time
        dict(origin="real"),  # origin enum
        dict(origin="measured", quality="maybe"),
        dict(origin="measured", quality="ok", invalid_reason="range"),
        dict(origin="measured", quality="invalid"),  # invalid needs a reason
    ):
        session.add(TelemetrySample(**{**base, **bad}))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_unique_key_and_fk_restrict_are_enforced(session):
    sid = (await session.execute(select(Sensor.id).where(Sensor.external_id == "temp"))).scalar_one()
    row = dict(
        sensor_id=sid,
        stream_id=LIVE,
        ts_event=NOW,
        ts_ingest=NOW,
        value=1.0,
        quality="ok",
        origin="measured",
        batch_id=uuid.uuid4(),
    )
    session.add(TelemetrySample(**row))
    await session.flush()
    session.add(TelemetrySample(**row))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_batch_is_atomic_when_the_caller_rolls_back(session):
    await ingest(session, [smp(ts=NOW - timedelta(seconds=i)) for i in range(5)], commit=False)
    await session.rollback()
    assert await rows(session) == []


# --------------------------------------------------------------------------- metrics
def _counter(outcome: str) -> float:
    return metrics.registry.get_sample_value("telemetry_samples_total", {"outcome": outcome}) or 0.0


async def test_counters_move_and_are_exported_on_metrics_text(session):
    before = {o: _counter(o) for o in v.OUTCOMES}
    b0 = metrics.registry.get_sample_value("telemetry_ingest_batches_total") or 0.0
    await ingest(
        session, [smp(value=1.0), smp(value=1.0), smp(value=2.0), smp("nope"), smp(ts=NOW + timedelta(seconds=9))]
    )
    assert _counter("accepted") - before["accepted"] == 1
    assert _counter("duplicate") - before["duplicate"] == 1
    assert _counter("conflict") - before["conflict"] == 1
    assert _counter("unknown_sensor") - before["unknown_sensor"] == 1
    assert _counter("invalid_future") - before["invalid_future"] == 1
    assert metrics.registry.get_sample_value("telemetry_ingest_batches_total") == b0 + 1
    body, _ctype = metrics.render_metrics()
    text_ = body.decode()
    assert "telemetry_ingest_batches_total" in text_
    for o in v.OUTCOMES:
        assert f'telemetry_samples_total{{outcome="{o}"}}' in text_


# --------------------------------------------------------------------------- PG-only: concurrency + EXPLAIN
@pytest.mark.skipif(not PG_URL, reason="TWINGRID_TEST_PG_ASYNC_URL not set")
@pytest.mark.parametrize("same_value", [True, False])
async def test_pg_two_concurrent_sessions_same_key_yield_one_row(db, same_value):
    if db.kind != "pg":
        pytest.skip("PostgreSQL only")
    async with db.maker() as s0:
        await _seed_sensors(s0)
    a, b = db.maker(), db.maker()
    try:
        ra = await ingest_samples(a, [smp(value=1.0)], stream_id=LIVE, origin="measured", now=NOW)  # uncommitted
        assert ra.counts[v.ACCEPTED] == 1
        task_b = asyncio.create_task(
            ingest_samples(b, [smp(value=1.0 if same_value else 2.0)], stream_id=LIVE, origin="measured", now=NOW)
        )
        await asyncio.sleep(0.4)
        assert not task_b.done(), "second writer must wait on the first writer's uncommitted unique key"
        await a.commit()
        rb = await asyncio.wait_for(task_b, 10)
        await b.commit()
    finally:
        await a.close()
        await b.close()
    assert rb.counts[v.DUPLICATE if same_value else v.CONFLICT] == 1 and rb.stored == 0
    async with db.maker() as chk:
        (row,) = await rows(chk)
        assert row.value == 1.0  # first write wins


@pytest.mark.skipif(not PG_URL, reason="TWINGRID_TEST_PG_ASYNC_URL not set")
async def test_pg_many_parallel_writers_one_row_total(db):
    if db.kind != "pg":
        pytest.skip("PostgreSQL only")
    async with db.maker() as s0:
        await _seed_sensors(s0)

    async def writer(i: int):
        async with db.maker() as s:
            r = await ingest_samples(s, [smp(value=1.0)], stream_id=LIVE, origin="measured", now=NOW)
            await s.commit()
            return r.counts[v.ACCEPTED]

    accepted = await asyncio.gather(*(writer(i) for i in range(8)))
    assert sum(accepted) == 1
    async with db.maker() as chk:
        assert len(await rows(chk)) == 1


RANGE_SQL = (
    "SELECT ts_event, value FROM telemetry_sample WHERE sensor_id = :sid AND stream_id = 'live' "
    "AND ts_event >= :lo AND ts_event < :hi ORDER BY ts_event"
)


async def _plan(db, session, rows_n: int):
    sid = (await session.execute(select(Sensor.id).where(Sensor.external_id == "temp"))).scalar_one()
    for start in range(0, rows_n, 1000):
        await ingest(
            session,
            [smp(ts=NOW - timedelta(seconds=i), value=float(i % 90)) for i in range(start, min(start + 1000, rows_n))],
        )
    params = {"sid": sid, "lo": NOW - timedelta(seconds=600), "hi": NOW}
    if db.kind == "pg":
        await session.execute(text("ANALYZE telemetry_sample"))
        res = await session.execute(text("EXPLAIN " + RANGE_SQL), params)
    else:
        res = await session.execute(text("EXPLAIN QUERY PLAN " + RANGE_SQL), params)
    return "\n".join(" | ".join(str(c) for c in r) for r in res.all())


async def test_explain_range_read_uses_the_unique_index(db, session):
    plan = await _plan(db, session, 3000)
    if db.kind == "pg":
        assert "uq_telemetry_sensor_stream_event" in plan and "Seq Scan" not in plan, plan
    else:
        assert (
            "USING INDEX sqlite_autoindex_telemetry_sample_1" in plan or "uq_telemetry_sensor_stream_event" in plan
        ), plan
        assert "SCAN telemetry_sample" not in plan.replace("USING", "SCAN-USING"), plan


# --------------------------------------------------------------------------- migration
def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "JWT_SECRET_KEY": "x",
        "ENVIRONMENT": "development",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )


def _sqlite_objects(db_path: Path):
    import sqlite3

    c = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in c.execute("PRAGMA table_info(sensor)")} if "sensor" in tables else set()
    finally:
        c.close()
    return tables, cols


T9_REV, T16_REV = "20261002000000", "20261003000000"


@pytest.fixture
def t9_db(tmp_path):
    """A DB at the T9 revision. Older migrations use PostgreSQL-only SQL, so (like test_facility_migration)
    build the T9 schema from the T9 migration itself on minimal stand-in legacy tables, then stamp."""
    import sqlite3

    db = tmp_path / "t16.db"
    with sqlite3.connect(db) as c:
        for t in ("sensor_readings", "alerts", "simulation_runs"):
            c.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTOINCREMENT, marker TEXT)")
            c.execute(f"INSERT INTO {t} (marker) VALUES ('pre-existing')")
    assert _alembic(db, "stamp", "20250223000000").returncode == 0
    r = _alembic(db, "upgrade", T9_REV)
    assert r.returncode == 0, r.stderr[-2000:]
    return db


def test_migration_up_down_up(t9_db):
    assert "telemetry_sample" not in _sqlite_objects(t9_db)[0]
    r = _alembic(t9_db, "upgrade", T16_REV)
    assert r.returncode == 0, r.stderr[-2000:]
    tables, cols = _sqlite_objects(t9_db)
    assert "telemetry_sample" in tables and "source_tz" in cols and "sensor_readings" in tables
    r = _alembic(t9_db, "downgrade", "-1")
    assert r.returncode == 0, r.stderr[-2000:]
    tables, cols = _sqlite_objects(t9_db)
    assert "telemetry_sample" not in tables and "source_tz" not in cols
    assert "sensor" in tables and "sensor_readings" in tables  # T9 + legacy untouched
    assert {"measurand", "unit", "min_valid"} <= cols
    r = _alembic(t9_db, "upgrade", T16_REV)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "telemetry_sample" in _sqlite_objects(t9_db)[0]


def test_migration_and_orm_define_the_same_columns_and_constraints(t9_db):
    import sqlite3

    assert _alembic(t9_db, "upgrade", T16_REV).returncode == 0
    c = sqlite3.connect(t9_db)
    try:
        mig = {r[1]: bool(r[3]) for r in c.execute("PRAGMA table_info(telemetry_sample)")}
        ddl = (
            c.execute("SELECT sql FROM sqlite_master WHERE name='telemetry_sample'").scalar()
            if False
            else c.execute("SELECT sql FROM sqlite_master WHERE name='telemetry_sample'").fetchone()[0]
        )
        sensor_default = [r for r in c.execute("PRAGMA table_info(sensor)") if r[1] == "source_tz"][0]
    finally:
        c.close()
    orm = {col.name: not col.nullable for col in TelemetrySample.__table__.columns}
    assert set(mig) == set(orm)
    assert {k: v_ for k, v_ in mig.items() if k != "id"} == {k: v_ for k, v_ in orm.items() if k != "id"}
    for name in (
        "uq_telemetry_sensor_stream_event",
        "ck_telemetry_origin",
        "ck_telemetry_sim_time_iff_simulated",
        "ck_telemetry_invalid_reason",
    ):
        assert name in ddl
    assert sensor_default[3] == 1 and sensor_default[4] in ("'UTC'", "UTC")  # NOT NULL DEFAULT 'UTC'


# --------------------------------------------------------------------------- seed (facility-level sensors)
def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_facility_t16", ROOT / "scripts" / "seed_facility.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _anomaly_feature_columns() -> list[str]:
    tree = ast.parse((ROOT / "src" / "anomaly_detector.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "FEATURE_COLUMNS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("FEATURE_COLUMNS not found")


async def test_seed_registers_the_five_anomaly_feature_sensors_idempotently(db):
    seed = _load_seed()
    async with db.maker() as s:
        await repo.insert_facility(s, name=seed.DEFAULT_FACILITY_NAME)
        assert await seed.seed_facility_sensors(s) == 5
        await s.commit()
        assert await seed.seed_facility_sensors(s) == 0  # idempotent
        await s.commit()
        sensors = (await s.execute(select(Sensor).order_by(Sensor.id))).scalars().all()
        assert [x.measurand for x in sensors] == _anomaly_feature_columns()
        assert all(x.sampling_interval_s == 300.0 and x.source_tz == "UTC" and x.unit for x in sensors)
        assert all(x.min_valid is not None and x.max_valid is not None for x in sensors)
        # the seeded sensors are usable by the writer
        fid = sensors[0].external_id
        r = await ingest(
            s,
            [{"external_id": fid, "ts_event": _iso(NOW), "value": 12.0, "unit": "L/min"}],
            origin="simulated" if False else "measured",
        )
        assert r.counts[v.ACCEPTED] == 1


async def test_seed_sensors_need_an_existing_facility(db):
    seed = _load_seed()
    async with db.maker() as s:
        with pytest.raises(RuntimeError):
            await seed.seed_facility_sensors(s)


# --------------------------------------------------------------------------- sole writer + shape
def test_ingest_samples_is_the_only_writer_of_telemetry_sample():
    offenders = []
    for d in ("api", "models", "src", "scripts", "database.py"):
        base = ROOT / d
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if rel == "src/telemetry/ingest.py":
                continue
            src = f.read_text(encoding="utf-8")
            # api/services/telemetry_window.py has its own unrelated in-memory dataclass of the same name;
            # only references to the ORM model / the table are writers-in-waiting.
            if "from models.db_models import" not in src and "telemetry_sample" not in src:
                continue
            if "TelemetrySample" not in src and "telemetry_sample" not in src:
                continue
            tree = ast.parse(src)
            # A class of the same name DEFINED in this file (the in-memory dataclass in telemetry_window.py) is not the
            # ORM model, so constructing it is not a write to the table.
            local_classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                    arg_names = {getattr(a, "id", getattr(a, "attr", "")) for a in node.args}
                    if (name == "TelemetrySample" and name not in local_classes) or (
                        name in {"insert", "delete", "update"} and "TelemetrySample" in arg_names
                    ):
                        offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, f"only src/telemetry/ingest.py may write telemetry_sample: {offenders}"


def test_sample_table_has_no_denormalised_facility_id_and_matches_9_1():
    cols = {c.name: c for c in TelemetrySample.__table__.columns}
    assert set(cols) == {
        "id",
        "sensor_id",
        "stream_id",
        "ts_event",
        "ts_ingest",
        "value",
        "quality",
        "invalid_reason",
        "origin",
        "sim_time",
        "batch_id",
    }
    assert "facility_id" not in cols and cols["origin"].default is None and cols["origin"].server_default is None
    assert all(cols[c].type.timezone for c in ("ts_event", "ts_ingest", "sim_time"))
    assert cols["stream_id"].type.length == 64 and cols["quality"].type.length == 8
    assert cols["invalid_reason"].type.length == 16 and cols["origin"].type.length == 16
    fk = next(iter(cols["sensor_id"].foreign_keys))
    assert fk.ondelete == "RESTRICT"
    assert math.isclose(v.FUTURE_TOLERANCE.total_seconds(), 5.0)
