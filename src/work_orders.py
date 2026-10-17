"""Maintenance work orders (Task 28): the status flow, the roles and the text rules. Pure: no database, no clock.

A work order is a RECORD that somebody should look at an asset: TwinGrid dispatches nothing and changes no equipment.
It can be raised by hand, from an alert, or from a health warning. Anything derived from an alert or a health row is
tagged ``origin = "simulated"`` (the data that triggered it is simulated); a hand-written one is ``"manual"``.
"""

from __future__ import annotations

from collections.abc import Mapping

OPEN, IN_PROGRESS, DONE, CANCELLED = "open", "in_progress", "done", "cancelled"
STATUSES: tuple[str, ...] = (OPEN, IN_PROGRESS, DONE, CANCELLED)
FINAL_STATUSES: tuple[str, ...] = (DONE, CANCELLED)

# from -> the statuses it may move to. done and cancelled are final (a new work order is raised instead).
TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    OPEN: (IN_PROGRESS, CANCELLED),
    IN_PROGRESS: (OPEN, DONE, CANCELLED),
    DONE: (),
    CANCELLED: (),
}

PRIORITIES: tuple[str, ...] = ("low", "medium", "high")
SOURCE_KINDS: tuple[str, ...] = ("manual", "alert", "health")

ORIGIN_SIMULATED = "simulated"
ORIGIN_MANUAL = "manual"

MAX_TITLE_CHARS = 160
MAX_DESCRIPTION_CHARS = 2000
MAX_NOTE_CHARS = 500
MAX_ASSIGNEE_CHARS = 64

RECORD_LABEL = "A work order is a record only. TwinGrid dispatches nothing and changes no equipment."


class TransitionError(ValueError):
    """The move is not allowed. ``code`` is client-safe: ``final`` or ``not_allowed``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_transition(current: str, target: str) -> None:
    """Raise ``TransitionError`` unless ``current -> target`` is in the table. A move to the same status is refused."""
    if current not in TRANSITIONS or target not in TRANSITIONS:
        raise TransitionError("not_allowed")
    if current in FINAL_STATUSES:
        raise TransitionError("final")
    if target not in TRANSITIONS[current]:
        raise TransitionError("not_allowed")


def next_statuses(current: str) -> tuple[str, ...]:
    return TRANSITIONS.get(current, ())


def can_write(role: str | None) -> bool:
    """Create and update: operator or admin. A viewer reads only."""
    return role in ("operator", "admin")


def origin_for(source_kind: str) -> str:
    return ORIGIN_MANUAL if source_kind == "manual" else ORIGIN_SIMULATED


def title_from_alert(alert_type: str, message: str) -> str:
    """A default title for a work order raised from an alert; cut to the title limit."""
    text = f"Investigate alert: {alert_type}" if not message.strip() else f"Investigate: {message.strip()}"
    return text if len(text) <= MAX_TITLE_CHARS else text[: MAX_TITLE_CHARS - 1].rstrip() + "…"


def title_from_health(asset_name: str, measurand: str | None, status: str) -> str:
    what = f"{asset_name} ({measurand})" if measurand else asset_name
    return f"Check {what}: health {status}"[:MAX_TITLE_CHARS]
