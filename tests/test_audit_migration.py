"""T15 migration 20261003000000 tests: up/down on SQLite, legacy backfill, and the PostgreSQL append-only trigger.

* SQLite runs the real Alembic CLI against a throw-away file (same pattern as tests/test_facility_migration.py):
  pre-T15 ``audit_logs`` is created from raw DDL and stamped at the previous revision.
* SQLite has NO trigger. ``test_sqlite_has_no_append_only_trigger_documented`` asserts that on purpose, so the
  gap is a tested, documented fact rather than an assumption: on SQLite UPDATE/DELETE on audit_logs succeed.
* The PostgreSQL trigger tests run only when TEST_POSTGRES_URL is set (e.g.
  ``postgresql+asyncpg://user:pw@localhost/twingrid_test``); they are skipped otherwise.
  The trigger guards against UPDATE/DELETE by any role; it is NOT immutability against a superuser/table owner.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREV, T15 = "20261002000000", "20261003000000"
MIGRATION_PATH = ROOT / "alembic" / "versions" / "20261003000000_t15_audit_log_completion.py"


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


def _cols(db: Path) -> set[str]:
    with sqlite3.connect(db) as c:
        return {r[1] for r in c.execute("PRAGMA table_info(audit_logs)")}


def _load_migration():
    spec = importlib.util.spec_from_file_location("t15_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pre_t15_db(tmp_path):
    """audit_logs exactly as created by 20250223000000, with two legacy rows, stamped at the previous head."""
    db = tmp_path / "t15.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)")
        c.execute(
            "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at DATETIME, user_id INTEGER, "
            "username VARCHAR(64), action VARCHAR(64) NOT NULL, resource_type VARCHAR(64), resource_id VARCHAR(64), "
            "details JSON, ip_address VARCHAR(64), FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL)"
        )
        c.execute("CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at)")
        c.execute("CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id)")
        c.execute("CREATE INDEX ix_audit_logs_action ON audit_logs (action)")
        c.execute(
            "INSERT INTO audit_logs (created_at, username, action, resource_type, resource_id, ip_address) "
            "VALUES ('2025-03-01', 'old-op', 'operator_registration', 'user', '1', '198.51.100.4')"
        )
        c.execute("INSERT INTO audit_logs (created_at, action) VALUES ('2025-03-02', 'alert_acknowledged')")
    r = _alembic(db, "stamp", PREV)
    assert r.returncode == 0, r.stderr
    return db


def test_upgrade_adds_columns_and_backfills_legacy_rows_as_success(pre_t15_db):
    r = _alembic(pre_t15_db, "upgrade", T15)
    assert r.returncode == 0, r.stderr
    cols = _cols(pre_t15_db)
    assert {"outcome", "request_id", "client_ip"} <= cols and "ip_address" not in cols
    with sqlite3.connect(pre_t15_db) as c:
        rows = c.execute("SELECT action, outcome, request_id, client_ip FROM audit_logs ORDER BY id").fetchall()
    assert rows == [
        ("operator_registration", "success", None, "198.51.100.4"),  # ip_address data preserved by the rename
        ("alert_acknowledged", "success", None, None),
    ]


def test_outcome_check_constraint_is_enforced(pre_t15_db):
    assert _alembic(pre_t15_db, "upgrade", T15).returncode == 0
    with sqlite3.connect(pre_t15_db) as c:
        c.execute("INSERT INTO audit_logs (action, outcome) VALUES ('x', 'denied')")
        c.execute("INSERT INTO audit_logs (action, outcome) VALUES ('x', 'failure')")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO audit_logs (action, outcome) VALUES ('x', 'maybe')")


def test_up_down_up_restores_original_columns_and_keeps_rows(pre_t15_db):
    for args in (("upgrade", T15), ("downgrade", "-1"), ("upgrade", T15)):
        r = _alembic(pre_t15_db, *args)
        assert r.returncode == 0, f"{args}: {r.stderr}"
    assert _alembic(pre_t15_db, "downgrade", "-1").returncode == 0
    cols = _cols(pre_t15_db)
    assert "ip_address" in cols and not ({"outcome", "request_id", "client_ip"} & cols)
    with sqlite3.connect(pre_t15_db) as c:
        assert c.execute("SELECT count(*), max(ip_address) FROM audit_logs").fetchone() == (2, "198.51.100.4")


def test_sqlite_has_no_append_only_trigger_documented(pre_t15_db):
    """DOCUMENTED GAP: only PostgreSQL gets the trigger. On SQLite, audit rows can be updated and deleted."""
    assert _alembic(pre_t15_db, "upgrade", T15).returncode == 0
    with sqlite3.connect(pre_t15_db) as c:
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone() == (0,)
        c.execute("UPDATE audit_logs SET action = 'tampered' WHERE id = 1")  # succeeds: no trigger
        c.execute("DELETE FROM audit_logs WHERE id = 2")  # succeeds: no trigger
        assert c.execute("SELECT count(*) FROM audit_logs WHERE action = 'tampered'").fetchone() == (1,)


def test_migration_sql_is_postgres_trigger_that_downgrade_drops():
    m = _load_migration()
    assert m.revision == T15 and m.down_revision == PREV
    assert "BEFORE UPDATE OR DELETE ON audit_logs" in m.CREATE_TRIGGER_SQL
    assert "restrict_violation" in m.CREATE_FUNCTION_SQL
    assert m.DROP_TRIGGER_SQL.startswith("DROP TRIGGER") and m.DROP_FUNCTION_SQL.startswith("DROP FUNCTION")


# ----------------------------------------------------------------------------- PostgreSQL (opt-in)
PG_URL = os.environ.get("TEST_POSTGRES_URL")
pg = pytest.mark.skipif(not PG_URL, reason="set TEST_POSTGRES_URL to run the PostgreSQL trigger tests")


@pytest.fixture
async def pg_engine():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from models.db_models import Base

    engine = create_async_engine(PG_URL)
    m = _load_migration()
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS audit_logs CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
        await conn.run_sync(Base.metadata.create_all)  # table shape from the ORM (includes T15 columns)
        await conn.exec_driver_sql(m.CREATE_FUNCTION_SQL)
        await conn.exec_driver_sql(m.CREATE_TRIGGER_SQL)
    yield engine
    async with engine.begin() as conn:
        await conn.exec_driver_sql(m.DROP_TRIGGER_SQL)
        await conn.exec_driver_sql(m.DROP_FUNCTION_SQL)
        await conn.execute(text("DROP TABLE IF EXISTS audit_logs CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
    await engine.dispose()


@pg
async def test_pg_trigger_allows_insert_rejects_update_and_delete(pg_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with pg_engine.begin() as conn:
        await conn.execute(text("INSERT INTO audit_logs (action, outcome) VALUES ('x', 'success')"))
    with pytest.raises(DBAPIError, match="append-only"):
        async with pg_engine.begin() as conn:
            await conn.execute(text("UPDATE audit_logs SET action = 'tampered'"))
    with pytest.raises(DBAPIError, match="append-only"):
        async with pg_engine.begin() as conn:
            await conn.execute(text("DELETE FROM audit_logs"))
    async with pg_engine.connect() as conn:
        assert (await conn.execute(text("SELECT action FROM audit_logs"))).scalars().all() == ["x"]


@pg
async def test_pg_user_deletion_still_nulls_actor_but_nothing_else_changes(pg_engine):
    """ON DELETE SET NULL on user_id is the single permitted UPDATE."""
    from sqlalchemy import text

    async with pg_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, username, hashed_password, role) VALUES (1, 'u', 'x', 'viewer')")
        )
        await conn.execute(
            text("INSERT INTO audit_logs (user_id, username, action, outcome) VALUES (1, 'u', 'logout', 'success')")
        )
    async with pg_engine.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id = 1"))
    async with pg_engine.connect() as conn:
        row = (await conn.execute(text("SELECT user_id, username, action FROM audit_logs"))).one()
    assert tuple(row) == (None, "u", "logout")


@pg
async def test_pg_rejects_other_updates_even_to_user_id(pg_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with pg_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, username, hashed_password, role) VALUES (1, 'u', 'x', 'viewer')")
        )
        await conn.execute(text("INSERT INTO audit_logs (user_id, action, outcome) VALUES (1, 'a', 'success')"))
    with pytest.raises(DBAPIError, match="append-only"):  # NULLing user_id AND changing another column
        async with pg_engine.begin() as conn:
            await conn.execute(text("UPDATE audit_logs SET user_id = NULL, action = 'b'"))
