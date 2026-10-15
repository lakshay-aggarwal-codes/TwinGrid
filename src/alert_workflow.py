"""Alert lifecycle rules (Task 17). Pure: no database, no clock, no framework.

Lifecycle: ``open`` -> ``acknowledged`` -> ``resolved`` (a skip straight to ``resolved`` is allowed, and an alert can be
re-opened). The stored state is the legacy ``alerts.acknowledged`` flag plus the nullable ``alerts.status`` column:

* ``status == "resolved"`` means resolved;
* otherwise the alert is ``acknowledged`` when the legacy flag is set (``POST /api/alerts/{id}/acknowledge`` keeps
  working and keeps meaning the same thing), else ``open``.

So alerts written before this task need no backfill and read as ``open`` / ``acknowledged`` exactly as they did.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

OPEN = "open"
ACKNOWLEDGED = "acknowledged"
RESOLVED = "resolved"
STATUSES: tuple[str, ...] = (OPEN, ACKNOWLEDGED, RESOLVED)

TRANSITIONS: Mapping[str, frozenset[str]] = {
    OPEN: frozenset({ACKNOWLEDGED, RESOLVED}),
    ACKNOWLEDGED: frozenset({OPEN, RESOLVED}),
    RESOLVED: frozenset({OPEN}),
}

MAX_NOTE_CHARS = 1000
MAX_ASSIGNEE_CHARS = 64


class InvalidTransition(ValueError):
    """``current`` -> ``target`` is not allowed. ``allowed`` lists what is (sorted, for a stable message)."""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        self.allowed = tuple(sorted(TRANSITIONS.get(current, frozenset())))
        super().__init__(f"cannot move an alert from {current} to {target}")


def effective_status(status: str | None, acknowledged: bool) -> str:
    """The lifecycle state of a stored alert (see the module docstring)."""
    if status == RESOLVED:
        return RESOLVED
    return ACKNOWLEDGED if acknowledged else OPEN


def check_transition(current: str, target: str) -> None:
    if target not in STATUSES:
        raise InvalidTransition(current, target)
    if target not in TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(current, target)


@dataclass(frozen=True)
class TimelineEntry:
    at: datetime | None
    kind: str  # created | status | assigned | note
    actor: str | None
    summary: str
    note: str | None = None


def _display(value: str | None) -> str:
    return value if value else "nobody"


def event_summary(kind: str, from_status: str | None, to_status: str | None, assignee: str | None) -> str:
    """One plain sentence for a stored event (the UI shows this text, not a colour)."""
    if kind == "status":
        return f"Status changed from {from_status} to {to_status}"
    if kind == "assigned":
        return f"Assigned to {_display(assignee)}" if assignee else "Unassigned"
    return "Note added"


def build_timeline(
    *,
    created_at: datetime | None,
    acknowledged: bool,
    acknowledged_by: str | None,
    acknowledged_at: datetime | None,
    events: list[Mapping[str, Any]],
) -> list[TimelineEntry]:
    """Oldest first: the detection itself, a legacy acknowledgement if no event records it, then the stored events.

    ``events`` are dicts with ``created_at, actor, kind, from_status, to_status, assignee, note`` already ordered by
    ``(created_at, id)``. A legacy acknowledgement (made through ``POST /acknowledge``, which writes no event) is
    shown once, from the alert's own acknowledged_* columns.
    """
    out = [TimelineEntry(created_at, "created", None, "Alert raised by the detector")]
    recorded_ack = any(e.get("kind") == "status" and e.get("to_status") == ACKNOWLEDGED for e in events)
    if acknowledged and acknowledged_at is not None and not recorded_ack:
        out.append(TimelineEntry(acknowledged_at, "status", acknowledged_by, "Acknowledged"))
    for e in events:
        out.append(
            TimelineEntry(
                e.get("created_at"),
                str(e.get("kind")),
                e.get("actor"),
                event_summary(str(e.get("kind")), e.get("from_status"), e.get("to_status"), e.get("assignee")),
                e.get("note"),
            )
        )
    return out
