"""T9 / M3 migration tests: up, down, up, with backfill evidence.

Runs the real Alembic CLI in a subprocess against a throw-away SQLite file.
Older migrations (e.g. 20250222300000 uses ``now()``) are PostgreSQL-flavoured, so the
pre-M3 schema is created from minimal raw DDL and stamped at the previous head; M3
itself is then exercised end to end. A PostgreSQL run is NOT covered here (see report).
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREV, M3 = "20250223000000", "20261002000000"
NEW_TABLES = {"facility", "asset", "asset_edge", "asset_pose", "sensor"}
OWNED = ("sensor_readings", "alerts", "simulation_runs")


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "JWT_SECRET_KEY": "x",
        "ENVIRONMENT": "development",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(db: Path, table: str) -> set[str]:
    with sqlite3.connect(db) as c:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def pre_m3_db(tmp_path):
    db = tmp_path / "m3.db"
    with sqlite3.connect(db) as c:
        for t in OWNED:  # minimal stand-ins: M3 only adds/drops facility_id on these
            c.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTOINCREMENT, marker TEXT)")
            c.execute(f"INSERT INTO {t} (marker) VALUES ('pre-existing')")
    r = _alembic(db, "stamp", PREV)
    assert r.returncode == 0, r.stderr
    return db


def test_single_alembic_head(tmp_path):
    r = _alembic(tmp_path / "x.db", "heads")
    assert r.returncode == 0, r.stderr
    assert M3 in r.stdout and r.stdout.count("(head)") == 1


def test_upgrade_creates_schema_default_facility_and_backfills(pre_m3_db):
    r = _alembic(pre_m3_db, "upgrade", M3)
    assert r.returncode == 0, r.stderr
    assert NEW_TABLES <= _tables(pre_m3_db)
    with sqlite3.connect(pre_m3_db) as c:
        fac = c.execute("SELECT id, name, frame_unit, frame_note FROM facility").fetchall()
        assert len(fac) == 1 and fac[0][1] == "Default Facility" and fac[0][2] == "m"
        assert "PENDING OWNER SIGN-OFF" in fac[0][3]  # scale not yet signed off
        for t in OWNED:
            assert "facility_id" in _cols(pre_m3_db, t)
            assert c.execute(f"SELECT facility_id FROM {t}").fetchall() == [(fac[0][0],)]
            assert c.execute(f"SELECT marker FROM {t}").fetchall() == [("pre-existing",)]  # data intact
        for t in ("asset", "asset_edge", "asset_pose", "sensor"):
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0  # seed is a separate step


def test_downgrade_removes_everything_and_keeps_old_data(pre_m3_db):
    assert _alembic(pre_m3_db, "upgrade", M3).returncode == 0
    r = _alembic(pre_m3_db, "downgrade", "-1")
    assert r.returncode == 0, r.stderr
    assert not (NEW_TABLES & _tables(pre_m3_db))
    for t in OWNED:
        assert "facility_id" not in _cols(pre_m3_db, t)
        with sqlite3.connect(pre_m3_db) as c:
            assert c.execute(f"SELECT marker FROM {t}").fetchall() == [("pre-existing",)]


def test_up_down_up(pre_m3_db):
    for args in (("upgrade", M3), ("downgrade", "-1"), ("upgrade", M3)):
        r = _alembic(pre_m3_db, *args)
        assert r.returncode == 0, f"{args}: {r.stderr}"
    assert NEW_TABLES <= _tables(pre_m3_db)


def test_migrated_schema_enforces_open_located_in_uniqueness(pre_m3_db):
    assert _alembic(pre_m3_db, "upgrade", M3).returncode == 0
    with sqlite3.connect(pre_m3_db) as c:
        fid = c.execute("SELECT id FROM facility").fetchone()[0]
        for ext, typ in (("z", "zone"), ("z2", "zone"), ("r", "rack")):
            c.execute(
                "INSERT INTO asset (facility_id, asset_type, external_id, name, created_at) VALUES (?,?,?,?, '2026-01-01')",
                (fid, typ, ext, ext),
            )
        ids = dict(c.execute("SELECT external_id, id FROM asset").fetchall())
        ins = "INSERT INTO asset_edge (parent_asset_id, child_asset_id, relation, valid_from) VALUES (?,?,?, '2026-01-01')"
        c.execute(ins, (ids["z"], ids["r"], "located_in"))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(ins, (ids["z2"], ids["r"], "located_in"))
