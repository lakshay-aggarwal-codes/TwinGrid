"""IG-05 / UQ-3 (ADR 006): ``data_repository.save_alert`` is the only code that writes an ``alerts`` row.

The gate scans ``api/``, ``src/`` and ``scripts/`` with the AST, so a new ``Alert(...)`` construction, an
``insert(Alert)`` or a raw ``INSERT INTO alerts`` outside the repository fails the build.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.db_models import Alert, Base

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("api", "src", "scripts")
WRITER = "api/repositories/data_repository.py"  # the one file allowed to construct an Alert row
_RAW_SQL = re.compile(r"insert\s+(or\s+\w+\s+)?into\s+alerts\b", re.IGNORECASE)


def offences(source: str) -> list[str]:
    """Every way ``source`` writes an alert row itself."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name == "Alert":
                found.append(f"line {node.lineno}: Alert(...)")
            elif name == "insert" and any(
                (isinstance(n, ast.Name) and n.id == "Alert") or (isinstance(n, ast.Attribute) and n.attr == "Alert")
                for n in ast.walk(node)
            ):
                found.append(f"line {node.lineno}: insert(Alert)")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _RAW_SQL.search(node.value):
            found.append(f"line {node.lineno}: raw INSERT INTO alerts")
    return found


def _python_files() -> list[Path]:
    return sorted(p for d in SCAN_DIRS for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts)


def test_no_alert_row_is_written_outside_the_repository():
    bad = {}
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == WRITER:
            continue
        hits = offences(path.read_text(encoding="utf-8"))
        if hits:
            bad[rel] = hits
    assert bad == {}, f"alert rows must be written only through data_repository.save_alert: {bad}"


def test_the_gate_is_not_vacuous():
    files = _python_files()
    assert len(files) > 50 and (ROOT / WRITER) in files
    assert offences((ROOT / WRITER).read_text(encoding="utf-8")), "the gate must see the real writer"
    assert offences("from models.db_models import Alert\nrow = Alert(score=1.0)\n")
    assert offences("import models.db_models as m\nrow = m.Alert(score=1.0)\n")
    assert offences("from sqlalchemy import insert\nstmt = insert(Alert).values(score=1)\n")
    assert offences("stmt = Alert.__table__.insert()\nx = insert(Alert.__table__)\n")
    assert offences('sql = "INSERT INTO alerts (score) VALUES (1)"\n')
    assert not offences("from models.db_models import Alert\nx: Alert | None = None\nsession.get(Alert, 1)\n")


def test_the_canonical_writer_is_used_by_the_pipeline_and_the_alert_manager():
    callers = {
        p.relative_to(ROOT).as_posix()
        for p in _python_files()
        if "save_alert(" in p.read_text(encoding="utf-8") and p.relative_to(ROOT).as_posix() != WRITER
    }
    assert {"api/services/anomaly_service.py", "src/alert_system.py"} <= callers


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)() as s:
        yield s
    await eng.dispose()


def _manager():
    from src.alert_system import AlertManager

    return AlertManager(enable_email=False, enable_slack=False)


async def test_alert_manager_rows_carry_origin_dedupe_key_and_model_version(session):
    sent = await _manager().raise_alert(
        session, "anomaly", "WARNING", "m", origin="simulated", score=0.4, dedupe_key="ep:1", model_version="sha256-x"
    )
    await session.commit()
    row = (await session.execute(select(Alert))).scalar_one()
    assert (row.origin, row.dedupe_key, row.model_version, row.severity, row.alert) == (
        "simulated", "ep:1", "sha256-x", "WARNING", True,
    )  # fmt: skip
    assert sent is True


async def test_alert_manager_repeat_with_the_same_dedupe_key_does_not_add_a_row(session):
    mgr = _manager()
    await mgr.raise_alert(session, "anomaly", "WARNING", "m", origin="simulated", dedupe_key="ep:2")
    await mgr.raise_alert(session, "anomaly", "CRITICAL", "m2", origin="simulated", dedupe_key="ep:2")
    await session.commit()
    assert len((await session.execute(select(Alert))).scalars().all()) == 1


async def test_alert_manager_refuses_an_alert_without_origin(session):
    with pytest.raises(TypeError):
        await _manager().raise_alert(session, "anomaly", "WARNING", "m")  # type: ignore[call-arg]
