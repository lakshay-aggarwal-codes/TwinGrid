"""Audit logging for sensitive actions: operator account creation,
POST /api/optimize triggers, and alert acknowledgment.

Append-only by design -- this module deliberately exposes no update/delete
helper. A mutable audit trail isn't an audit trail; if a row needs to go,
that's a direct DB operation with its own justification, not something this
service should make easy.

Failures here must never break the action being audited: if writing the
audit row fails, the caller's request should still succeed (a lost audit
entry is far less costly than a lost optimization run or a rejected
registration). Callers that can tolerate an extra flush point call
``log_action`` directly inside their own session/transaction; if that's a
concern for a given call site, wrap it in a try/except there.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import AuditLog, User


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None or request.client is None:
        return None
    return request.client.host


async def log_action(
    session: AsyncSession,
    *,
    action: str,
    user: Optional[User] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int | str] = None,
    details: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> AuditLog:
    """Record one audit-log entry and flush it in the current session.

    ``user`` is denormalized (id + username stored separately) so the trail
    still reads sensibly if the user account is later deleted.
    """
    entry = AuditLog(
        user_id=user.id if user is not None else None,
        username=user.username if user is not None else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=details,
        ip_address=_client_ip(request),
    )
    session.add(entry)
    await session.flush()
    return entry
