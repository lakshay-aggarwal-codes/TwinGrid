"""T12 -- time contract (roadmap §9.2).

Covers: the normalisation table tests, DST fold/gap, ``from_state_dict`` erroring instead of
substituting "now", ORM defaults, the twin's default clock, the live-payload hour, the AST guard
against naive clocks, and (optional) a Postgres round-trip under a non-UTC session time zone.
"""

from __future__ import annotations

import ast
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from src import timeutil
from src.timeutil import (
    TimeContractError,
    is_ambiguous_local,
    is_nonexistent_local,
    parse_timestamp,
    to_site_local,
    to_utc,
    utc_now,
)

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
NY = "America/New_York"


def _utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


# --------------------------------------------------------------------------- to_utc
@pytest.mark.parametrize(
    "dt, source_tz, expected",
    [
        # aware, positive and negative offsets, and UTC itself
        (datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))), None, _utc(2026, 1, 1, 6, 30)),
        (datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-8))), None, _utc(2026, 1, 1, 20, 0)),
        (datetime(2026, 1, 1, 12, 0, tzinfo=UTC), None, _utc(2026, 1, 1, 12, 0)),
        # aware value ignores source_tz (it carries its own offset)
        (datetime(2026, 1, 1, 12, 0, tzinfo=UTC), "Asia/Kolkata", _utc(2026, 1, 1, 12, 0)),
        # naive + tz
        (datetime(2026, 1, 1, 12, 0), "Asia/Kolkata", _utc(2026, 1, 1, 6, 30)),
        (datetime(2026, 7, 1, 12, 0), NY, _utc(2026, 7, 1, 16, 0)),  # EDT, -4
        (datetime(2026, 1, 1, 12, 0), NY, _utc(2026, 1, 1, 17, 0)),  # EST, -5
        (datetime(2026, 1, 1, 12, 0), "UTC", _utc(2026, 1, 1, 12, 0)),
    ],
)
def test_to_utc_table(dt, source_tz, expected):
    out = to_utc(dt, source_tz)
    assert out == expected
    assert out.tzinfo is not None and out.utcoffset() == timedelta(0)


def test_to_utc_accepts_a_tzinfo_object_as_source_tz():
    assert to_utc(datetime(2026, 1, 1, 12, 0), timezone(timedelta(hours=2))) == _utc(2026, 1, 1, 10, 0)


def test_naive_without_tz_is_an_error():
    with pytest.raises(TimeContractError):
        to_utc(datetime(2026, 1, 1, 12, 0))
    with pytest.raises(ValueError):  # TimeContractError is a ValueError
        to_utc(datetime(2026, 1, 1, 12, 0), None)


@pytest.mark.parametrize("bad", [None, "2026-01-01T00:00:00Z", 1767225600, 1.5])
def test_to_utc_rejects_non_datetimes(bad):
    with pytest.raises(TimeContractError):
        to_utc(bad)


def test_unknown_source_tz_is_an_error_not_utc():
    with pytest.raises(TimeContractError):
        to_utc(datetime(2026, 1, 1), "Mars/Olympus_Mons")
    with pytest.raises(TimeContractError):
        to_utc(datetime(2026, 1, 1), "   ")


# --------------------------------------------------------------------------- DST (America/New_York)
def test_dst_fold_is_the_first_occurrence_and_deterministic():
    # 2025-11-02 01:30 happens twice in New York (EDT then EST).
    wall = datetime(2025, 11, 2, 1, 30)
    assert is_ambiguous_local(wall, NY) and not is_nonexistent_local(wall, NY)
    first = to_utc(wall, NY)
    assert first == _utc(2025, 11, 2, 5, 30)  # 01:30 EDT (-4): the FIRST occurrence
    assert to_utc(wall, NY) == first  # repeatable
    # the second occurrence is reachable by supplying its offset explicitly
    assert to_utc(datetime(2025, 11, 2, 1, 30, tzinfo=timezone(timedelta(hours=-5)))) == _utc(2025, 11, 2, 6, 30)


def test_dst_gap_uses_the_pre_transition_offset_and_is_detectable():
    # 2025-03-09 02:30 never happens in New York (02:00 -> 03:00).
    wall = datetime(2025, 3, 9, 2, 30)
    assert is_nonexistent_local(wall, NY) and not is_ambiguous_local(wall, NY)
    assert to_utc(wall, NY) == _utc(2025, 3, 9, 7, 30)  # offset before the jump (EST, -5)
    assert to_utc(wall, NY) == to_utc(wall, NY)


@pytest.mark.parametrize("wall", [datetime(2025, 3, 9, 1, 59), datetime(2025, 3, 9, 3, 0), datetime(2025, 11, 2, 2, 0)])
def test_ordinary_wall_times_near_transitions_are_neither_ambiguous_nor_missing(wall):
    assert not is_ambiguous_local(wall, NY) and not is_nonexistent_local(wall, NY)


# --------------------------------------------------------------------------- parse_timestamp
@pytest.mark.parametrize(
    "text, source_tz, expected",
    [
        ("2026-01-01T12:00:00Z", None, _utc(2026, 1, 1, 12, 0)),
        ("2026-01-01T12:00:00z", None, _utc(2026, 1, 1, 12, 0)),
        ("2026-01-01T12:00:00+00:00", None, _utc(2026, 1, 1, 12, 0)),
        ("2026-01-01T12:00:00+05:30", None, _utc(2026, 1, 1, 6, 30)),
        ("2026-01-01T12:00:00-08:00", None, _utc(2026, 1, 1, 20, 0)),
        ("2026-01-01 12:00:00+05:30", None, _utc(2026, 1, 1, 6, 30)),
        ("2026-01-01T12:00:00.250Z", None, datetime(2026, 1, 1, 12, 0, 0, 250000, tzinfo=UTC)),
        ("  2026-01-01T12:00:00Z  ", None, _utc(2026, 1, 1, 12, 0)),
        ("2026-01-01T12:00:00", "Asia/Kolkata", _utc(2026, 1, 1, 6, 30)),
        ("2026-07-01T12:00:00", NY, _utc(2026, 7, 1, 16, 0)),
        ("2026-01-01T12:00:00+05:30", NY, _utc(2026, 1, 1, 6, 30)),  # explicit offset wins over source_tz
    ],
)
def test_parse_timestamp_table(text, source_tz, expected):
    out = parse_timestamp(text, source_tz)
    assert out == expected and out.utcoffset() == timedelta(0)


@pytest.mark.parametrize("bad", [None, "", "   ", "not a time", "2026-13-45T00:00:00Z", 12345, b"2026-01-01", [], {}])
def test_parse_timestamp_rejects_garbage(bad):
    with pytest.raises(TimeContractError):
        parse_timestamp(bad)


@pytest.mark.parametrize(
    "naive", ["2026-01-01T12:00:00", "2026-01-01 12:00:00", "2026-01-01", datetime(2026, 1, 1, 12)]
)
def test_parse_timestamp_naive_without_tz_is_an_error(naive):
    with pytest.raises(TimeContractError):
        parse_timestamp(naive)


def test_parse_timestamp_accepts_aware_datetimes():
    assert parse_timestamp(datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=1)))) == _utc(2026, 1, 1, 11)


def test_utc_now_is_aware_utc_and_close_to_the_wall_clock():
    before = datetime.now(UTC)
    now = utc_now()
    after = datetime.now(UTC)
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)
    assert before <= now <= after


# --------------------------------------------------------------------------- site zone
def test_site_timezone_default_is_asia_kolkata(monkeypatch):
    monkeypatch.delenv("SITE_TIMEZONE", raising=False)
    assert timeutil.site_timezone_name() == "Asia/Kolkata"
    assert to_site_local(_utc(2026, 1, 1, 6, 30)).replace(tzinfo=None) == datetime(2026, 1, 1, 12, 0)
    monkeypatch.setenv("SITE_TIMEZONE", "  ")
    assert timeutil.site_timezone_name() == "Asia/Kolkata"


def test_site_timezone_env_override_and_conversion(monkeypatch):
    monkeypatch.setenv("SITE_TIMEZONE", NY)
    assert to_site_local(_utc(2026, 7, 1, 16, 0)).hour == 12
    assert to_site_local(_utc(2026, 1, 1, 17, 0)).hour == 12
    # an aware non-UTC input is normalised first
    assert to_site_local(datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))).hour == 1


def test_to_site_local_rejects_naive_and_bad_zone(monkeypatch):
    with pytest.raises(TimeContractError):
        to_site_local(datetime(2026, 1, 1, 12))
    monkeypatch.setenv("SITE_TIMEZONE", "Not/AZone")
    with pytest.raises(TimeContractError):  # a bad config must not silently fall back to UTC
        to_site_local(_utc(2026, 1, 1))


def test_config_exposes_site_timezone_and_sim_step_seconds(monkeypatch):
    from api import config
    from src.digital_twin import INTERVAL_MINUTES

    monkeypatch.delenv("SIM_STEP_SECONDS", raising=False)
    assert config.DEFAULT_SIM_STEP_SECONDS == 300  # A-1
    assert config.sim_step_seconds() == 300 == INTERVAL_MINUTES * 60
    monkeypatch.setenv("SIM_STEP_SECONDS", "60")
    assert config.sim_step_seconds() == 60
    monkeypatch.setenv("SIM_STEP_SECONDS", "-5")
    assert config.sim_step_seconds() == 300  # invalid -> strict default
    assert config.DEFAULT_SITE_TIMEZONE == "Asia/Kolkata"


# --------------------------------------------------------------------------- ORM
STATE = {
    "timestamp": "2026-03-01T00:00:00Z",
    "server_utilisation": 0.5,
    "outside_temp_C": 20.0,
    "server_inlet_temp_C": 20.0,
    "server_outlet_temp_C": 30.0,
    "it_power_kw": 200.0,
    "cooling_power_kw": 50.0,
    "total_power_kw": 250.0,
    "pue": 1.25,
    "water_flow_lpm": 50.0,
    "water_consumed_L": 10.0,
    "wue": 1.0,
    "humidity_pct": 50.0,
    "water_pressure_bar": 3.0,
    "cooling_mode": "closed_loop",
}


def test_every_timestamptz_default_in_the_orm_is_the_single_clock():
    from sqlalchemy import DateTime

    from models.db_models import Base

    checked = 0
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, DateTime) and col.default is not None:
                assert col.type.timezone is True, f"{table.name}.{col.name} must be timezone=True"
                fn = col.default.arg
                # SQLAlchemy wraps a zero-arg callable as fn(ctx); unwrap to the original.
                assert (
                    getattr(fn, "__wrapped__", fn) is utc_now
                ), f"{table.name}.{col.name} default is {fn!r}, expected src.timeutil.utc_now"
                checked += 1
    assert checked >= 8


def test_orm_default_produces_aware_utc_on_flush():
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    from models.db_models import User

    engine = sa.create_engine("sqlite://")
    User.__table__.create(engine)
    before = datetime.now(UTC)
    with Session(engine) as s:
        u = User(username="t12", hashed_password="x")
        s.add(u)
        s.flush()
        assert u.created_at.tzinfo is not None and u.created_at.utcoffset() == timedelta(0)
        assert before <= u.created_at <= datetime.now(UTC)


def test_from_state_dict_normalises_to_aware_utc():
    from models.db_models import SensorReading

    r = SensorReading.from_state_dict({**STATE, "timestamp": "2026-03-01T05:30:00+05:30"}, "api")
    assert r.timestamp == _utc(2026, 3, 1, 0, 0) and r.timestamp.utcoffset() == timedelta(0)
    r = SensorReading.from_state_dict(
        {**STATE, "timestamp": datetime(2026, 3, 1, 1, tzinfo=timezone(timedelta(hours=1)))}, "api"
    )
    assert r.timestamp == _utc(2026, 3, 1, 0, 0)


@pytest.mark.parametrize("bad", [None, "", "garbage", "2026-03-01T00:00:00", datetime(2026, 3, 1)])
def test_from_state_dict_errors_instead_of_substituting_now(bad):
    from models.db_models import SensorReading

    with pytest.raises(TimeContractError):
        SensorReading.from_state_dict({**STATE, "timestamp": bad}, "api")
    state = dict(STATE)
    state.pop("timestamp")
    with pytest.raises(TimeContractError):
        SensorReading.from_state_dict(state, "api")


# --------------------------------------------------------------------------- twin default clock
def test_digital_twin_default_start_is_the_single_clock_and_explicit_start_is_untouched():
    from src.digital_twin import DigitalTwin

    before = datetime.now(UTC)
    twin = DigitalTwin(start_time=None)
    assert twin._time.tzinfo is not None and twin._time.utcoffset() == timedelta(0)
    assert before <= twin._time <= datetime.now(UTC)
    explicit = datetime(2025, 6, 1, 3, 0, 0)  # naive explicit start: caller's choice, unchanged (goldens rely on it)
    assert DigitalTwin(start_time=explicit)._time == explicit


# --------------------------------------------------------------------------- ingestion
def _payload(ts):
    return {
        **STATE,
        "timestamp": ts,
        "server_inlet_temp_C": 20.0,
    }


def test_ingestion_accepts_aware_offsets_and_rejects_naive_and_garbage():
    from src.sensor_ingestion import payload_to_state_dict, validate_sensor_payload

    now = utc_now()
    ok, err = validate_sensor_payload(_payload(now.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()))
    assert ok, err
    ok, err = validate_sensor_payload(_payload(now.replace(tzinfo=None).isoformat()))
    assert not ok and "timestamp" in err.lower()  # naive is NOT assumed to be UTC
    ok, err = validate_sensor_payload(_payload("garbage"))
    assert not ok
    ok, err = validate_sensor_payload(_payload(None))
    assert not ok
    state = payload_to_state_dict(_payload("2026-03-01T05:30:00+05:30"))
    assert state["timestamp"] == _utc(2026, 3, 1, 0, 0)
    with pytest.raises(TimeContractError):  # no substitution of "now"
        payload_to_state_dict(_payload("2026-03-01T05:30:00"))


def test_synthetic_payload_timestamp_is_aware_utc():
    from src.sensor_ingestion import generate_synthetic_payload

    ts = datetime.fromisoformat(generate_synthetic_payload()["timestamp"])
    assert ts.utcoffset() == timedelta(0)


# --------------------------------------------------------------------------- live payload hour
def test_live_payload_hour_equals_to_site_local_hour(monkeypatch):
    """The diurnal hour used by the live tick is the SITE-local hour of the tick's clock read."""
    import api.services.live_broadcast_service as lbs
    from tests.characterization import golden_support as gs

    instant = _utc(2026, 1, 1, 7, 0)  # 12:30 in Asia/Kolkata, 07:00 in UTC
    seen: dict[str, float] = {}

    real_site_local = lbs.to_site_local

    def spy(dt):
        out = real_site_local(dt)
        seen["hour"] = out.hour + out.minute / 60
        return out

    async def go():
        with gs.live_tick_environment():
            with mock.patch.dict(os.environ, {"SITE_TIMEZONE": "Asia/Kolkata"}):
                with mock.patch.object(lbs, "utc_now", lambda: instant), mock.patch.object(lbs, "to_site_local", spy):
                    return await lbs._tick()

    payload = asyncio.run(go())
    expected_hour = _site(instant, "Asia/Kolkata").hour + _site(instant, "Asia/Kolkata").minute / 60
    assert seen["hour"] == expected_hour == 12.5  # site-local, NOT the UTC hour (7.0)
    expected_util = float(np.clip(0.4 + 0.5 * np.sin((expected_hour - 6) * np.pi / 12), 0, 1))
    assert payload["server_utilisation"] == pytest.approx(expected_util, rel=1e-9)
    assert payload["ts_ingest"] == instant.isoformat()  # same clock read, aware UTC


def _site(dt: datetime, name: str) -> datetime:
    from zoneinfo import ZoneInfo

    return dt.astimezone(ZoneInfo(name))


# --------------------------------------------------------------------------- AST guard
GUARDED_DIRS = ("api", "models", "src")

# file (repo-relative) -> number of naive-clock calls tolerated there, with the reason.
# Every entry is debt that T12's allowed-file list did not let it fix; the count is pinned so
# a NEW naive call in the same file still fails.
ALLOW_LIST: dict[str, tuple[int, str]] = {
    "src/digital_twin_optimized.py": (
        2,
        "legacy optimised twin; not an allowed T12 file. Two live `start_time or datetime.now()` defaults "
        "(the other two hits are docstring examples, invisible to the AST).",
    ),
}

_NAIVE_ATTRS_ALWAYS = {"utcnow", "utcfromtimestamp"}


def _is_datetime_base(node: ast.AST) -> bool:
    # datetime.now / datetime.datetime.now / date.today
    if isinstance(node, ast.Name):
        return node.id in {"datetime", "date"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"datetime", "date"}
    return False


def naive_clock_calls(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr, base = node.func.attr, node.func.value
        if attr in _NAIVE_ATTRS_ALWAYS and _is_datetime_base(base):
            hits.append((node.lineno, f"{attr}()"))
        elif attr == "today" and _is_datetime_base(base):
            hits.append((node.lineno, "today()"))
        elif attr in {"now", "fromtimestamp"} and _is_datetime_base(base):
            has_tz = len(node.args) >= (1 if attr == "now" else 2) or any(k.arg == "tz" for k in node.keywords)
            if not has_tz:
                hits.append((node.lineno, f"{attr}() without tz"))
            else:
                tz_arg = node.args[0 if attr == "now" else 1] if node.args[0 if attr == "now" else 1 :] else None
                if tz_arg is None:
                    tz_arg = next((k.value for k in node.keywords if k.arg == "tz"), None)
                if isinstance(tz_arg, ast.Constant) and tz_arg.value is None:
                    hits.append((node.lineno, f"{attr}(None)"))
    return hits


def _scan() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for d in GUARDED_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            hits = naive_clock_calls(path.read_text(encoding="utf-8"))
            if hits:
                found[path.relative_to(ROOT).as_posix()] = hits
    return found


def test_ast_guard_no_naive_clock_outside_the_allow_list():
    found = _scan()
    unexpected = {f: h for f, h in found.items() if f not in ALLOW_LIST}
    assert not unexpected, f"naive clock calls (use src.timeutil.utc_now): {unexpected}"
    for f, (count, _why) in ALLOW_LIST.items():
        assert len(found.get(f, [])) <= count, f"{f}: more naive clock calls than the pinned allow-list ({count})"


def test_allow_list_has_no_stale_entries():
    found = _scan()
    for f in ALLOW_LIST:
        assert f in found, f"{f} no longer has naive clock calls -- remove it from ALLOW_LIST"


@pytest.mark.parametrize(
    "src, n",
    [
        ("import datetime\ndatetime.datetime.utcnow()", 1),
        ("from datetime import datetime\ndatetime.utcnow()", 1),
        ("from datetime import datetime\ndatetime.now()", 1),
        ("from datetime import datetime\ndatetime.now(None)", 1),
        ("from datetime import datetime\ndatetime.today()", 1),
        ("from datetime import datetime\ndatetime.fromtimestamp(0)", 1),
        ("from datetime import datetime\ndatetime.utcfromtimestamp(0)", 1),
        ("from datetime import datetime, timezone\ndatetime.now(timezone.utc)", 0),
        ("from datetime import datetime, timezone\ndatetime.now(tz=timezone.utc)", 0),
        ("from datetime import datetime, timezone\ndatetime.fromtimestamp(0, tz=timezone.utc)", 0),
        ("from datetime import datetime, timezone\ndatetime.fromtimestamp(0, timezone.utc)", 0),
        ("x = other.now()", 0),
    ],
)
def test_ast_guard_detector_self_test(src, n):
    assert len(naive_clock_calls(src)) == n


def test_golden_support_freezes_the_one_clock_not_a_module_datetime():
    """Guard the harness itself: a frozen clock must reach the twin default via src.timeutil."""
    from src.digital_twin import DigitalTwin
    from tests.characterization import golden_support as gs

    with gs.frozen_environment():
        assert DigitalTwin()._time == gs.FIXED_NOW_UTC


# --------------------------------------------------------------------------- Postgres (optional)
PG_URL = os.getenv("TWINGRID_TEST_PG_URL")


@pytest.mark.skipif(not PG_URL, reason="set TWINGRID_TEST_PG_URL (sync psycopg2 URL) to run the Postgres round-trip")
def test_postgres_orm_default_round_trips_as_aware_utc_under_a_non_utc_session_zone():
    import sqlalchemy as sa
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from models.db_models import User

    schema = "t12_time"
    engine = sa.create_engine(PG_URL)

    @event.listens_for(engine, "connect")
    def _set_zone(dbapi_conn, _record):  # session time zone != UTC on every pooled connection
        cur = dbapi_conn.cursor()
        cur.execute("SET TIME ZONE 'Asia/Kolkata'")
        cur.close()

    try:
        with engine.begin() as conn:
            conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
            conn.execute(sa.text(f"SET search_path TO {schema}"))
            assert conn.execute(sa.text("SHOW TIME ZONE")).scalar() == "Asia/Kolkata"
            User.__table__.create(conn)
            assert str(User.__table__.c.created_at.type.compile(engine.dialect)) == "TIMESTAMP WITH TIME ZONE"

        before = datetime.now(UTC)
        with Session(engine) as s:
            s.connection().execute(sa.text(f"SET search_path TO {schema}"))
            s.add(User(username="t12-aware", hashed_password="x"))  # created_at <- ORM default utc_now
            s.commit()
            row = (
                s.connection()
                .execute(
                    sa.text("SELECT created_at, created_at AT TIME ZONE 'UTC' FROM users WHERE username='t12-aware'")
                )
                .one()
            )
        after = datetime.now(UTC)
        stored, as_utc_wall = row
        assert stored.tzinfo is not None
        assert before <= stored.astimezone(UTC) <= after  # same instant, whatever zone the session renders it in
        assert stored.utcoffset() == timedelta(hours=5, minutes=30)  # the session zone really is Kolkata
        assert as_utc_wall.tzinfo is None and as_utc_wall.replace(tzinfo=UTC) == stored.astimezone(UTC)

        # Why this task exists (F-6): a NAIVE utcnow() written under the same session zone is read as
        # Kolkata local time, so the stored instant is 5h30m wrong.
        with engine.begin() as conn:
            conn.execute(sa.text(f"SET search_path TO {schema}"))
            naive = datetime.now(UTC).replace(tzinfo=None)  # what datetime.utcnow() returns
            conn.execute(
                sa.text(
                    "INSERT INTO users (username, hashed_password, role, created_at) VALUES ('naive','x','viewer',:t)"
                ),
                {"t": naive},
            )
            wrong = conn.execute(sa.text("SELECT created_at FROM users WHERE username='naive'")).scalar()
        assert abs((datetime.now(UTC) - wrong.astimezone(UTC)) - timedelta(hours=5, minutes=30)) < timedelta(seconds=30)
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
