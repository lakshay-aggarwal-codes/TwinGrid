"""T10: the schema is defined by ONE linear Alembic chain, and the ORM equals it.

* Structure tests read the revision files only (no database).
* Round-trip and ``alembic check`` run the real Alembic CLI in a subprocess against a
  throw-away SQLite file (same approach as tests/test_facility_migration.py).

PostgreSQL is NOT exercised here; the manual PostgreSQL 16 run is recorded in
reports/postT9/T10_evidence.md.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("alembic")
pytest.importorskip("aiosqlite")

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The intended order of the five provenance/facility/audit/telemetry migrations, after the last legacy one.
LEGACY_HEAD = "20250223000000"
M1, M2, M3 = "20261001000000", "20261001000001", "20261002000000"
# M4 = T15 (audit-log completion); M5 = T16 (telemetry_sample, renumbered from 20261003000000).
M4, M5 = "20261003000000", "20261004000000"


def _script() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "JWT_SECRET_KEY": "ci-test-secret-not-for-production",
        "ENVIRONMENT": "development",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
    )


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ----------------------------------------------------------------------------- structure


def test_single_head():
    assert _script().get_heads() == [M5]


def test_revision_ids_are_unique():
    revisions = [path.name for path in (ROOT / "alembic" / "versions").glob("*.py")]
    script = _script()
    ids = [rev.revision for rev in script.walk_revisions()]
    assert len(ids) == len(set(ids)) == len(revisions)


def test_chain_is_linear_and_in_the_agreed_order():
    script = _script()
    ordered = [rev.revision for rev in script.walk_revisions("base", "heads")][::-1]  # oldest first
    assert ordered[-6:] == [LEGACY_HEAD, M1, M2, M3, M4, M5]
    for rev in script.walk_revisions():
        assert not rev.is_branch_point, f"{rev.revision} has more than one child"
        assert not rev.is_merge_point, f"{rev.revision} is a merge point"
    assert script.get_revision(M1).down_revision == LEGACY_HEAD
    assert script.get_revision(M2).down_revision == M1
    assert script.get_revision(M3).down_revision == M2
    assert script.get_revision(M4).down_revision == M3
    assert script.get_revision(M5).down_revision == M4


# ----------------------------------------------------------------------------- SQLite round trip


def test_upgrade_downgrade_upgrade_on_sqlite(tmp_path):
    db = tmp_path / "chain.db"

    up = _alembic(db, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert {"sensor_readings", "alerts", "facility", "asset", "sensor"} <= _tables(db)

    down = _alembic(db, "downgrade", "base")
    assert down.returncode == 0, down.stderr
    assert _tables(db) <= {"alembic_version"}  # every application table is gone

    again = _alembic(db, "upgrade", "head")
    assert again.returncode == 0, again.stderr

    current = _alembic(db, "current")
    assert current.returncode == 0, current.stderr
    assert M5 in current.stdout


def test_orm_matches_migrations_no_autogenerate_diff(tmp_path):
    db = tmp_path / "check.db"
    up = _alembic(db, "upgrade", "head")
    assert up.returncode == 0, up.stderr

    check = _alembic(db, "check")
    assert check.returncode == 0, f"alembic check reported drift:\n{check.stdout}\n{check.stderr}"
