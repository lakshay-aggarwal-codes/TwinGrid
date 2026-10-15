"""Task 17: the pure lifecycle rules (src/alert_workflow.py) and the additive migration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src import alert_workflow as wf
from tests.test_alembic_chain import M5, M6, _alembic

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 1, 8, 5, tzinfo=timezone.utc)


def test_effective_status_reads_legacy_rows_unchanged():
    assert wf.effective_status(None, False) == "open"
    assert wf.effective_status(None, True) == "acknowledged"
    assert wf.effective_status("open", False) == "open"
    assert wf.effective_status("acknowledged", True) == "acknowledged"
    assert wf.effective_status("resolved", False) == "resolved"
    assert wf.effective_status("resolved", True) == "resolved"  # resolved wins over the legacy flag


ALLOWED = {
    ("open", "acknowledged"),
    ("open", "resolved"),
    ("acknowledged", "open"),
    ("acknowledged", "resolved"),
    ("resolved", "open"),
}


@pytest.mark.parametrize("current", wf.STATUSES)
@pytest.mark.parametrize("target", wf.STATUSES)
def test_every_transition_pair(current, target):
    if (current, target) in ALLOWED:
        wf.check_transition(current, target)
    else:
        with pytest.raises(wf.InvalidTransition) as exc:
            wf.check_transition(current, target)
        assert exc.value.current == current and exc.value.target == target


def test_unknown_target_is_refused():
    with pytest.raises(wf.InvalidTransition):
        wf.check_transition("open", "closed")


def test_timeline_shows_a_legacy_acknowledgement_once():
    entries = wf.build_timeline(created_at=T0, acknowledged=True, acknowledged_by="op1", acknowledged_at=T1, events=[])
    assert [(e.kind, e.actor, e.summary) for e in entries] == [
        ("created", None, "Alert raised by the detector"),
        ("status", "op1", "Acknowledged"),
    ]


def test_timeline_does_not_duplicate_an_acknowledgement_that_has_an_event():
    events = [
        {"created_at": T1, "actor": "op1", "kind": "status", "from_status": "open", "to_status": "acknowledged"},
        {"created_at": T1, "actor": "op1", "kind": "assigned", "assignee": "op2"},
        {"created_at": T1, "actor": "op2", "kind": "assigned", "assignee": None},
        {"created_at": T1, "actor": "op2", "kind": "note", "note": "checked the CRAC"},
    ]
    entries = wf.build_timeline(
        created_at=T0, acknowledged=True, acknowledged_by="op1", acknowledged_at=T1, events=events
    )
    assert [e.summary for e in entries] == [
        "Alert raised by the detector",
        "Status changed from open to acknowledged",
        "Assigned to op2",
        "Unassigned",
        "Note added",
    ]
    assert entries[-1].note == "checked the CRAC"


def test_migration_adds_columns_and_table_and_downgrades_cleanly(tmp_path):
    db = tmp_path / "t17.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(alerts)")}
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        event_cols = {r[1] for r in c.execute("PRAGMA table_info(alert_events)")}
    assert {"status", "assignee", "resolved_by", "resolved_at"} <= cols
    assert "alert_events" in tables
    assert {"alert_id", "created_at", "actor", "kind", "from_status", "to_status", "assignee", "note"} <= event_cols

    down = _alembic(db, "downgrade", M5)
    assert down.returncode == 0, down.stderr
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(alerts)")}
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not ({"status", "assignee", "resolved_by", "resolved_at"} & cols)
    assert "alert_events" not in tables
    assert {"dedupe_key", "origin", "acknowledged"} <= cols  # earlier columns untouched
    assert M6 not in _alembic(db, "current").stdout
