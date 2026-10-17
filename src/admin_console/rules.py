"""Task 29: the admin console's rules. Pure: no I/O, no FastAPI, no database.

* Only the exact role ``admin`` administers. Anything else (viewer, operator, an unknown string, missing) is refused.
* A role change cannot be made on yourself and cannot remove the last admin.
* Audit filters are validated, never clamped; an export is bounded and its cells are neutralised against spreadsheet
  formula injection (a username such as ``=cmd|...`` is attacker-controlled data in the audit log).
* A webhook is shown by an id (a fingerprint of its URL), its scheme, host and port. Never its path, query or userinfo:
  webhook URLs routinely carry secret tokens.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

ROLES: tuple[str, ...] = ("viewer", "operator", "admin")
OUTCOMES: tuple[str, ...] = ("success", "denied", "failure")

AUDIT_PAGE_DEFAULT = 50
AUDIT_PAGE_MAX = 200
EXPORT_MAX_ROWS = 10_000
MAX_FILTER_CHARS = 64
USERS_MAX = 500


def can_administer(role: Optional[str]) -> bool:
    return role == "admin"


# ----------------------------------------------------------------------------- role changes

ROLE_CHANGE_MESSAGES: dict[str, str] = {
    "invalid_role": "Role must be viewer, operator or admin.",
    "own_role": "You cannot change your own role.",
    "unchanged": "That user already has this role.",
    "last_admin": "The last admin cannot be demoted.",
}


def check_role_change(
    *, actor_id: int, target_id: int, current_role: str, new_role: str, admin_count: int
) -> Optional[str]:
    """``None`` if the change is allowed, else a code from ``ROLE_CHANGE_MESSAGES`` (the API answers 409; 422 for a role
    that does not exist at the schema level)."""
    if new_role not in ROLES:
        return "invalid_role"
    if actor_id == target_id:
        return "own_role"
    if new_role == current_role:
        return "unchanged"
    if current_role == "admin" and new_role != "admin" and admin_count <= 1:
        return "last_admin"
    return None


# ----------------------------------------------------------------------------- audit filters


class FilterError(ValueError):
    """An audit filter is invalid (the API maps this to a 422)."""


@dataclass(frozen=True)
class AuditFilters:
    action: Optional[str] = None
    outcome: Optional[str] = None
    username: Optional[str] = None
    resource_type: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    before_id: Optional[int] = None

    def as_details(self) -> dict[str, Any]:
        """The filters in use, for the export's audit row (only the ones set)."""
        out: dict[str, Any] = {}
        for name in ("action", "outcome", "username", "resource_type", "before_id"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        for name in ("since", "until"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name).isoformat()
        return out


def _text(name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if len(v) > MAX_FILTER_CHARS:
        raise FilterError(f"{name} is longer than {MAX_FILTER_CHARS} characters")
    return v


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_filters(
    *,
    action: Optional[str] = None,
    outcome: Optional[str] = None,
    username: Optional[str] = None,
    resource_type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    before_id: Optional[int] = None,
) -> AuditFilters:
    out = _text("outcome", outcome)
    if out is not None and out not in OUTCOMES:
        raise FilterError(f"outcome must be one of: {', '.join(OUTCOMES)}")
    if before_id is not None and (isinstance(before_id, bool) or not isinstance(before_id, int) or before_id < 1):
        raise FilterError("before_id must be a positive whole number")
    s, u = _utc(since), _utc(until)
    if s is not None and u is not None and s > u:
        raise FilterError("since is after until")
    return AuditFilters(
        action=_text("action", action),
        outcome=out,
        username=_text("username", username),
        resource_type=_text("resource_type", resource_type),
        since=s,
        until=u,
        before_id=before_id,
    )


# ----------------------------------------------------------------------------- export

EXPORT_COLUMNS: tuple[str, ...] = (
    "id",
    "created_at",
    "username",
    "action",
    "outcome",
    "resource_type",
    "resource_id",
    "client_ip",
    "request_id",
    "details",
)
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    """A cell that a spreadsheet will read as text, never as a formula (OWASP CSV injection guidance)."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_LEADERS) else text


def export_cell(column: str, value: Any) -> str:
    if column == "details":
        return "" if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "" if value is None else str(value)


def to_csv(rows: list[Mapping[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow([csv_safe(export_cell(c, row.get(c))) for c in EXPORT_COLUMNS])
    return buf.getvalue()


def to_json(rows: list[Mapping[str, Any]]) -> str:
    return json.dumps([{c: row.get(c) for c in EXPORT_COLUMNS} for row in rows], sort_keys=True, default=str)


def export_filename(now: datetime, fmt: str) -> str:
    return f"audit-log-{_utc(now):%Y%m%dT%H%M%SZ}.{fmt}"


# ----------------------------------------------------------------------------- webhooks


def webhook_id(url: str) -> str:
    """Stable, non-reversible id (same value as ``audit_service.url_fingerprint``)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def webhook_view(url: str) -> dict[str, Any]:
    """What the console may show of a subscriber: id, scheme, host, port. Never the path, query or credentials."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = None
    return {"id": webhook_id(url), "scheme": parts.scheme, "host": (parts.hostname or ""), "port": port}


def find_webhook(urls: list[str], wid: str) -> Optional[str]:
    """The registered URL whose id is ``wid``, if any."""
    for u in urls:
        if webhook_id(u) == wid:
            return u
    return None
