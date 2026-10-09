"""T1b / M1: provenance migration + ORM model + old-writer compatibility.

The migration is exercised directly (alembic Operations on an in-memory SQLite
engine) against a minimal pre-M1 schema, because the earlier migrations in the
chain use Postgres-only ALTERs. Postgres evidence (full chain up/down/up and the
index EXPLAIN) is produced by the commands in the T1b report and the optional
test at the bottom (needs TWINGRID_TEST_PG_URL).
"""

import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from models.db_models import Base, OptimizationResult, SensorReading, SimulationRun
from src.versions import KNOWN_PHYSICS_VERSIONS, LEGACY_PHYSICS_VERSION, ORIGIN_SIMULATED, PHYSICS_VERSION

ROOT = Path(__file__).resolve().parent.parent
M1_PATH = ROOT / "alembic" / "versions" / "20261001000000_m1_provenance.py"
NEW_COLUMNS = {
    "sensor_readings": {"origin", "physics_version"},
    "simulation_runs": {"physics_version"},
    "optimization_results": {"physics_version", "model_version"},
}


def _load_m1():
    spec = importlib.util.spec_from_file_location("m1_provenance", M1_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(engine, fn):
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            fn()


def _columns(engine, table):
    return {c["name"]: c for c in sa.inspect(engine).get_columns(table)}


def _indexes(engine, table):
    return {i["name"] for i in sa.inspect(engine).get_indexes(table)}


@pytest.fixture
def pre_m1_engine():
    """Minimal pre-M1 tables (only what the migration touches), with legacy rows."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE sensor_readings (id INTEGER PRIMARY KEY, timestamp DATETIME NOT NULL)"))
        conn.execute(sa.text("CREATE TABLE simulation_runs (id INTEGER PRIMARY KEY, hours INTEGER NOT NULL)"))
        conn.execute(sa.text("CREATE TABLE optimization_results (id INTEGER PRIMARY KEY, hours INTEGER NOT NULL)"))
        conn.execute(
            sa.text("INSERT INTO sensor_readings (timestamp) VALUES ('2026-01-01 00:00:00'), ('2026-01-01 01:00:00')")
        )
        conn.execute(sa.text("INSERT INTO simulation_runs (hours) VALUES (24)"))
        conn.execute(sa.text("INSERT INTO optimization_results (hours) VALUES (24), (48)"))
    yield engine
    engine.dispose()


# ----------------------------------------------------------------------------- constants / chain


def test_physics_version_constant():
    # The M1 backfill label is frozen at "legacy-0"; the version new work runs under has since moved on.
    assert LEGACY_PHYSICS_VERSION == "legacy-0"
    assert PHYSICS_VERSION in KNOWN_PHYSICS_VERSIONS
    assert ORIGIN_SIMULATED == "simulated"


def test_m1_follows_the_previous_head_and_is_in_the_chain():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    # The single-head / full-order checks live in tests/test_alembic_chain.py; M1 stays on the legacy head.
    assert script.get_revision("20261001000000").down_revision == "20250223000000"


# ----------------------------------------------------------------------------- upgrade / backfill


def test_upgrade_adds_columns_index_and_backfills_existing_rows(pre_m1_engine):
    _run(pre_m1_engine, _load_m1().upgrade)

    for table, names in NEW_COLUMNS.items():
        assert names <= set(_columns(pre_m1_engine, table))
    assert "ix_sensor_readings_timestamp" in _indexes(pre_m1_engine, "sensor_readings")

    with pre_m1_engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT origin, physics_version FROM sensor_readings")).all()
        assert rows == [("simulated", "legacy-0")] * 2
        assert conn.execute(sa.text("SELECT physics_version FROM simulation_runs")).scalars().all() == ["legacy-0"]
        assert (
            conn.execute(sa.text("SELECT physics_version FROM optimization_results")).scalars().all()
            == ["legacy-0"] * 2
        )
        assert conn.execute(sa.text("SELECT model_version FROM optimization_results")).scalars().all() == [None] * 2


def test_upgrade_columns_match_the_orm_models(pre_m1_engine):
    _run(pre_m1_engine, _load_m1().upgrade)
    for table, names in NEW_COLUMNS.items():
        orm_cols = Base.metadata.tables[table].c
        db_cols = _columns(pre_m1_engine, table)
        for name in names:
            assert db_cols[name]["nullable"] == orm_cols[name].nullable, (table, name)
            assert db_cols[name]["type"].length == orm_cols[name].type.length, (table, name)
    origin_default = str(_columns(pre_m1_engine, "sensor_readings")["origin"]["default"])
    assert "simulated" in origin_default
    assert "ix_sensor_readings_timestamp" in {i.name for i in Base.metadata.tables["sensor_readings"].indexes}


def test_downgrade_then_upgrade_is_clean(pre_m1_engine):
    m1 = _load_m1()
    _run(pre_m1_engine, m1.upgrade)
    _run(pre_m1_engine, m1.downgrade)

    for table, names in NEW_COLUMNS.items():
        assert not names & set(_columns(pre_m1_engine, table)), table
    assert "ix_sensor_readings_timestamp" not in _indexes(pre_m1_engine, "sensor_readings")
    with pre_m1_engine.connect() as conn:  # data rows survive the round trip
        assert conn.execute(sa.text("SELECT count(*) FROM sensor_readings")).scalar_one() == 2
        assert conn.execute(sa.text("SELECT count(*) FROM optimization_results")).scalar_one() == 2

    _run(pre_m1_engine, m1.upgrade)
    with pre_m1_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT DISTINCT origin FROM sensor_readings")).scalars().all() == ["simulated"]
        assert conn.execute(sa.text("SELECT DISTINCT physics_version FROM sensor_readings")).scalars().all() == [
            "legacy-0"
        ]


def test_old_style_insert_without_new_columns_still_succeeds(pre_m1_engine):
    _run(pre_m1_engine, _load_m1().upgrade)
    with pre_m1_engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO sensor_readings (timestamp) VALUES ('2026-02-01 00:00:00')"))
        conn.execute(sa.text("INSERT INTO simulation_runs (hours) VALUES (6)"))
        conn.execute(sa.text("INSERT INTO optimization_results (hours) VALUES (6)"))
    with pre_m1_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT origin, physics_version FROM sensor_readings ORDER BY id DESC LIMIT 1")
        ).one()
    assert row == ("simulated", None)  # default origin; no physics label for an old-style writer


# ----------------------------------------------------------------------------- ORM


STATE = {
    "timestamp": "2026-03-01T00:00:00+00:00",
    "server_utilisation": 0.5,
    "outside_temp_C": 25.0,
    "server_inlet_temp_C": 22.0,
    "server_outlet_temp_C": 35.0,
    "it_power_kw": 300.0,
    "cooling_power_kw": 90.0,
    "total_power_kw": 390.0,
    "pue": 1.3,
    "water_flow_lpm": 100.0,
    "water_consumed_L": 10.0,
    "wue": 0.4,
    "humidity_pct": 40.0,
    "water_pressure_bar": 3.0,
    "cooling_mode": "auto",
}


def _orm_engine():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_from_state_dict_without_provenance_leaves_defaults_to_the_database():
    reading = SensorReading.from_state_dict(STATE, "api")
    assert reading.origin is None and reading.physics_version is None  # not set in Python
    engine = _orm_engine()
    with Session(engine) as session:
        session.add(reading)
        session.commit()
        session.expire_all()
        stored = session.execute(sa.select(SensorReading)).scalar_one()
        assert (stored.origin, stored.physics_version) == ("simulated", None)


def test_from_state_dict_carries_explicit_provenance():
    reading = SensorReading.from_state_dict(
        STATE, "ws", origin=ORIGIN_SIMULATED, physics_version=LEGACY_PHYSICS_VERSION
    )
    assert (reading.origin, reading.physics_version) == ("simulated", "legacy-0")
    assert reading.timestamp == datetime(2026, 3, 1, tzinfo=timezone.utc)


def test_model_declares_the_m1_columns_and_index():
    cols = Base.metadata.tables["sensor_readings"].c
    assert cols.origin.nullable is False and cols.origin.type.length == 16
    assert cols.physics_version.nullable is True and cols.physics_version.type.length == 32
    assert cols.timestamp.index is True
    assert Base.metadata.tables["simulation_runs"].c.physics_version.nullable is True
    assert Base.metadata.tables["optimization_results"].c.model_version.nullable is True
    assert SimulationRun.__table__ is Base.metadata.tables["simulation_runs"]
    assert OptimizationResult.__table__ is Base.metadata.tables["optimization_results"]


# ----------------------------------------------------------------------------- Postgres only


@pytest.mark.skipif(
    not os.getenv("TWINGRID_TEST_PG_URL"),
    reason="set TWINGRID_TEST_PG_URL (sync psycopg/psycopg2 URL)",
)
def test_postgres_timestamp_range_query_uses_the_new_index():
    engine = sa.create_engine(os.environ["TWINGRID_TEST_PG_URL"])
    schema = "t1b_explain"
    with engine.begin() as conn:
        conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
        conn.execute(sa.text(f"SET search_path TO {schema}"))
        conn.execute(sa.text("CREATE TABLE sensor_readings (id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ NOT NULL)"))
        conn.execute(sa.text("CREATE TABLE simulation_runs (id SERIAL PRIMARY KEY, hours INTEGER NOT NULL)"))
        conn.execute(sa.text("CREATE TABLE optimization_results (id SERIAL PRIMARY KEY, hours INTEGER NOT NULL)"))
        conn.execute(
            sa.text(
                "INSERT INTO sensor_readings (timestamp) "
                "SELECT TIMESTAMPTZ '2026-01-01' + (g || ' minutes')::interval FROM generate_series(1, 20000) g"
            )
        )
        with Operations.context(MigrationContext.configure(conn)):
            _load_m1().upgrade()
        conn.execute(sa.text("ANALYZE sensor_readings"))
        plan = "\n".join(
            conn.execute(
                sa.text(
                    "EXPLAIN SELECT * FROM sensor_readings "
                    "WHERE timestamp >= '2026-01-05' AND timestamp < '2026-01-06'"
                )
            )
            .scalars()
            .all()
        )
        conn.execute(sa.text(f"DROP SCHEMA {schema} CASCADE"))
    assert "ix_sensor_readings_timestamp" in plan, plan
