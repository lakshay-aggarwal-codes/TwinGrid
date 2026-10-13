"""Task 5: the demo seed (scripts/demo_seed.py) and the demo launch files.

Runs against in-memory SQLite like the other repository tests (no Postgres, no Docker).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")  # api.auth refuses to import without it

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from api.auth import verify_password  # noqa: E402
from models.db_models import Alert, Base, Facility, Sensor, SimulationRun, TelemetrySample, User  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 13, 9, 7, 31, tzinfo=timezone.utc)


def _load(name: str):
    """Load scripts/<name>.py by path (scripts/ is not a package)."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


demo_seed = _load("demo_seed")


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)() as s:
        yield s
    await eng.dispose()


async def _count(session, model) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


# ---- DEMO_MODE guard -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "false", "0", "yes", "1", "truee"])
def test_demo_mode_is_off_unless_exactly_true(value):
    env = {} if value is None else {"DEMO_MODE": value}
    assert demo_seed.demo_mode_enabled(env) is False
    with pytest.raises(demo_seed.DemoModeRequired):
        demo_seed.require_demo_mode(env)


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_demo_mode_true_is_accepted(value):
    assert demo_seed.demo_mode_enabled({"DEMO_MODE": value}) is True


def test_main_refuses_without_demo_mode_and_never_touches_the_database(monkeypatch, capsys):
    monkeypatch.delenv("DEMO_MODE", raising=False)

    def boom():  # would be the database run
        raise AssertionError("the seed must not start without DEMO_MODE=true")

    monkeypatch.setattr(demo_seed, "_run", boom)
    assert demo_seed.main() == 2
    assert "DEMO_MODE=true" in capsys.readouterr().err


# ---- the seed itself -------------------------------------------------------------------------------------------


async def test_seed_populates_every_area_and_labels_it_simulated(session):
    result = await demo_seed.seed_demo(session, now=NOW)
    await session.commit()

    assert await _count(session, Facility) == 1
    assert await _count(session, Sensor) == 5

    steps = 24 * 3600 // 300
    assert await _count(session, TelemetrySample) == steps * 5 == result.telemetry_stored
    rows = (await session.execute(select(TelemetrySample))).scalars().all()
    assert {r.origin for r in rows} == {"simulated"}  # the seed never writes `measured`
    assert {r.stream_id for r in rows} == {"live"}
    assert all(r.sim_time is not None and r.quality == "ok" for r in rows)
    stamps = {r.ts_event.replace(tzinfo=timezone.utc) if r.ts_event.tzinfo is None else r.ts_event for r in rows}
    assert max(stamps) == datetime(2026, 10, 13, 9, 5, tzinfo=timezone.utc)  # last whole 5-minute step <= now
    assert max(stamps) - min(stamps) == timedelta(hours=24) - timedelta(minutes=5)

    assert await _count(session, SimulationRun) == len(demo_seed.DEMO_RUNS) == result.runs_created
    alerts = (await session.execute(select(Alert))).scalars().all()
    assert len(alerts) == len(demo_seed.DEMO_ALERTS) == result.alerts_created
    assert {a.origin for a in alerts} == {"simulated"}
    assert all(a.dedupe_key and a.dedupe_key.startswith("demo-seed:") for a in alerts)
    assert {a.severity for a in alerts} <= {"WARNING", "CRITICAL"}


async def test_rerun_with_the_same_clock_changes_nothing(session):
    first = await demo_seed.seed_demo(session, now=NOW)
    await session.commit()
    before = {
        m.__name__: await _count(session, m) for m in (User, Facility, Sensor, TelemetrySample, SimulationRun, Alert)
    }

    second = await demo_seed.seed_demo(session, now=NOW)
    await session.commit()
    after = {
        m.__name__: await _count(session, m) for m in (User, Facility, Sensor, TelemetrySample, SimulationRun, Alert)
    }

    assert after == before
    assert (second.users_created, second.passwords) == ([], {})
    assert (second.telemetry_stored, second.runs_created, second.alerts_created) == (0, 0, 0)
    assert first.users_created  # sanity: the first run did create accounts


async def test_a_later_rerun_only_adds_the_new_telemetry_tail(session):
    await demo_seed.seed_demo(session, now=NOW)
    await session.commit()
    later = NOW + timedelta(minutes=20)  # 09:27:31 -> window ends 09:25: four new steps x five sensors
    again = await demo_seed.seed_demo(session, now=later)
    await session.commit()
    assert again.telemetry_stored == 4 * 5
    assert (again.runs_created, again.alerts_created, again.users_created) == (0, 0, [])


# ---- accounts and passwords --------------------------------------------------------------------------------------


async def test_three_accounts_with_distinct_generated_passwords_stored_only_as_hashes(session):
    result = await demo_seed.seed_demo(session, now=NOW)
    await session.commit()

    users = {u.username: u for u in (await session.execute(select(User))).scalars().all()}
    assert {n: u.role for n, u in users.items()} == {
        "demo_viewer": "viewer",
        "demo_operator": "operator",
        "demo_admin": "admin",
    }
    assert set(result.passwords) == set(users)
    passwords = list(result.passwords.values())
    assert len(set(passwords)) == 3
    for name, password in result.passwords.items():
        assert len(password) >= 16
        assert users[name].hashed_password != password and password not in users[name].hashed_password
        assert verify_password(password, users[name].hashed_password)


async def test_an_existing_account_keeps_its_password(session):
    from api.auth import hash_password

    session.add(User(username="demo_viewer", hashed_password=hash_password("keep-me-please"), role="viewer"))
    await session.commit()
    result = await demo_seed.seed_demo(session, now=NOW)
    await session.commit()
    assert "demo_viewer" not in result.passwords
    assert sorted(result.users_created) == ["demo_admin", "demo_operator"]
    viewer = (await session.execute(select(User).where(User.username == "demo_viewer"))).scalar_one()
    assert verify_password("keep-me-please", viewer.hashed_password)


async def test_passwords_never_reach_logs_or_output_except_the_one_printed_report(session, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    result = await demo_seed.seed_demo(session, now=NOW)
    await session.commit()
    captured = capsys.readouterr()
    for password in result.passwords.values():
        assert password not in caplog.text
        assert password not in captured.out + captured.err  # seed_demo itself prints nothing
    report = demo_seed.format_report(result)
    assert all(p in report for p in result.passwords.values())  # the report is how they are shown, once
    assert "stored nowhere" in report


def test_the_report_of_a_rerun_prints_no_credentials():
    text = demo_seed.format_report(demo_seed.DemoSeedResult(facility_id=1))
    assert "not recoverable" in text and "demo_" not in text


# ---- the synthetic pattern ---------------------------------------------------------------------------------------


def test_telemetry_pattern_is_deterministic_and_inside_the_sensor_valid_ranges():
    seed_facility = _load("seed_facility")
    ranges = {m: (lo, hi) for m, _unit, lo, hi in seed_facility.FACILITY_SENSORS}
    ids = {m: f"fac1.{m}" for m in ranges}
    one = demo_seed.build_samples(ids, NOW)
    two = demo_seed.build_samples(ids, NOW)
    assert one == two
    assert len(one) == 288 * 5
    for s in one:
        feature = s["external_id"].split(".", 1)[1]
        lo, hi = ranges[feature]
        assert lo < s["value"] < hi


# ---- launch files: no credentials committed ----------------------------------------------------------------------

LAUNCH_FILES = ("scripts/demo.ps1", "scripts/demo.sh", "docker-compose.demo.yml")
LITERAL_SECRET = re.compile(r"(?i)(password|secret|token)\w*\s*[=:]\s*[\"']?[A-Za-z0-9]{8,}")


@pytest.mark.parametrize("rel", LAUNCH_FILES)
def test_launch_files_exist_and_assign_no_literal_secret(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert text.strip()
    assert LITERAL_SECRET.search(text) is None


def test_launch_files_never_write_the_demo_user_passwords_anywhere():
    for rel in LAUNCH_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"demo_(viewer|operator|admin)", text), rel


def test_the_demo_env_file_is_git_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore").splitlines()
    assert ".env.*" in [line.strip() for line in ignore]


def test_the_overlay_does_not_replace_the_base_compose_file():
    overlay = (ROOT / "docker-compose.demo.yml").read_text(encoding="utf-8")
    assert "DEMO_MODE" in overlay and "demo-seed" in overlay
    assert "-f docker-compose.yml -f docker-compose.demo.yml" in (ROOT / "scripts/demo.sh").read_text(encoding="utf-8")
    assert "docker-compose.demo.yml" in (ROOT / "scripts/demo.ps1").read_text(encoding="utf-8")
