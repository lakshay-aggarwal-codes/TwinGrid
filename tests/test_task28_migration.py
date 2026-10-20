"""Task 28: the work-orders migration is additive, sits at the end of the single chain, and round-trips on SQLite.

Structure tests read the revision file only. The round trip runs the real Alembic CLI against a throw-away SQLite file
(same approach as tests/test_alembic_chain.py, which also runs ``alembic check``: the ORM must equal this migration).
"""

from __future__ import annotations

import os
import re
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
REV, PARENT = "20261008000000", "20261007000000"
FILE = ROOT / "alembic" / "versions" / "20261008000000_t28_work_orders.py"
NEW_TABLES = {"work_orders", "work_order_events"}


def _script() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "JWT_SECRET_KEY": "ci-test-secret-not-for-production",
        "ENVIRONMENT": "development",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
    )


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_the_revision_is_the_single_head_and_revises_the_previous_one():
    script = _script()
    assert script.get_heads() == ["20261101000000"]  # T9 (access_requests) is the head now; this revision is its parent
    assert script.get_revision("20261101000000").down_revision == REV
    rev = script.get_revision(REV)
    assert rev.down_revision == PARENT and not rev.is_branch_point and not rev.is_merge_point


def test_the_migration_only_creates_tables_and_indexes_and_drops_them_on_downgrade():
    src = FILE.read_text()
    up, down = src.split("def upgrade()")[1].split("def downgrade()")
    assert set(re.findall(r'op\.create_table\(\s*"(\w+)"', up)) == NEW_TABLES
    assert set(re.findall(r'op\.drop_table\("(\w+)"\)', down)) == NEW_TABLES
    for forbidden in ("op.add_column", "op.drop_column", "op.alter_column", "op.execute", "op.rename_table"):
        assert forbidden not in up, f"{forbidden} would change an existing table"
    assert "drop_column" not in down and "add_column" not in down


def test_every_work_order_row_carries_origin_and_status_is_not_nullable():
    up = FILE.read_text().split("def upgrade()")[1].split("def downgrade()")[0]
    assert re.search(r'sa\.Column\("origin", sa\.String\(16\), nullable=False\)', up)
    assert re.search(r'sa\.Column\("status", sa\.String\(16\), nullable=False\)', up)
    assert 'ondelete="CASCADE"' in up  # events go with their order


def test_upgrade_creates_the_tables_and_downgrade_removes_only_them(tmp_path):
    db = tmp_path / "t28.db"
    assert _alembic(db, "upgrade", PARENT).returncode == 0
    before = _tables(db)
    assert not (NEW_TABLES & before)
    up = _alembic(db, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert NEW_TABLES <= _tables(db)
    down = _alembic(db, "downgrade", PARENT)
    assert down.returncode == 0, down.stderr
    assert _tables(db) == before  # nothing else was touched
    again = _alembic(db, "upgrade", "head")
    assert again.returncode == 0, again.stderr


def test_existing_rows_survive_the_upgrade(tmp_path):
    db = tmp_path / "t28_rows.db"
    assert _alembic(db, "upgrade", PARENT).returncode == 0
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO facility (name, frame_unit, frame_note, created_at) VALUES ('keep-me', 'm', '', '2026-10-01T00:00:00+00:00')"
        )
        c.commit()
    assert _alembic(db, "upgrade", "head").returncode == 0
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT name FROM facility WHERE name='keep-me'").fetchone() == ("keep-me",)
