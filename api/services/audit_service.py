"""Audit logging for privileged actions (roadmap 8.4, T15).

Two write modes, chosen per event (see ``EVENT_MODES``):

* **Atomic** -- ``log_action(session, ...)``. The row is added to the CALLER's session and flushed,
  so it commits or rolls back together with the action it records. If the audit write fails the
  exception propagates (as ``AuditWriteError``) and the action is aborted: ``get_db`` rolls the
  whole transaction back. Call it BEFORE any non-transactional side effect (enqueueing a job,
  mutating the webhook file) so a failed audit write prevents that effect.
* **Best-effort** -- ``log_action_best_effort(...)``. The row is written in an INDEPENDENT session
  and committed immediately, so it survives the request's own rollback (denied / failed requests).
  It never raises: any failure is logged and counted in ``audit_write_failures_total``.

Append-only: this module exposes no update/delete helper, and on PostgreSQL a trigger installed by
migration 20261003000000 rejects UPDATE/DELETE on ``audit_logs``. That is a DB-enforced guard against
application bugs and ordinary roles; it is NOT immutability against a superuser / the table owner.

``client_ip`` follows ``api.rate_limit.client_ip`` (X-Forwarded-For honoured only behind a trusted
proxy, nearest ``TRUSTED_PROXY_HOPS`` entry). If that resolver cannot run, the socket peer is used --
never an unverified header. ``details`` is scrubbed of secret-looking keys before it is stored.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlsplit

from fastapi import Request
from prometheus_client import Counter
from sqlalchemy.ext.asyncio import AsyncSession

from api import rate_limit
from api.middleware.metrics import registry as metrics_registry
from api.middleware.request_id import request_id_var
from models.db_models import (
    AUDIT_OUTCOME_DENIED,
    AUDIT_OUTCOME_FAILURE,
    AUDIT_OUTCOME_SUCCESS,
    AUDIT_OUTCOMES,
    AuditLog,
    User,
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- events

MODE_ATOMIC = "atomic"
MODE_BEST_EFFORT = "best_effort"

# action -> write mode (roadmap 8.4 table). The read-only GET endpoints are deliberately absent.
EVENT_MODES: dict[str, str] = {
    "operator_registration": MODE_ATOMIC,
    "login_success": MODE_BEST_EFFORT,
    "login_failure": MODE_BEST_EFFORT,
    "refresh_reuse_detected": MODE_BEST_EFFORT,
    "logout": MODE_BEST_EFFORT,
    "permission_denied": MODE_BEST_EFFORT,
    "optimize_triggered": MODE_ATOMIC,
    "train_async_enqueued": MODE_ATOMIC,
    "webhook_registered": MODE_ATOMIC,
    "webhook_unregistered": MODE_ATOMIC,
    "alert_acknowledged": MODE_ATOMIC,
    "asset_move": MODE_ATOMIC,
    "asset_edge_create": MODE_ATOMIC,
    "asset_edge_close": MODE_ATOMIC,
    # Model lifecycle: written by the T19/T30 CLI through log_model_event (no caller in this snapshot).
    "model_promoted": MODE_ATOMIC,
    "model_rejected": MODE_ATOMIC,
    "model_quarantined": MODE_ATOMIC,
}
MODEL_EVENT_ACTIONS = ("model_promoted", "model_rejected", "model_quarantined")

# ----------------------------------------------------------------------------- metrics

# Registered on the API registry so it is exposed by GET /metrics.
AUDIT_WRITE_FAILURES = Counter(
    "audit_write_failures_total",
    "Best-effort audit rows that could not be written (the audited request was not affected)",
    registry=metrics_registry,
)


class AuditWriteError(RuntimeError):
    """An atomic audit write failed; the audited action must not proceed / must roll back."""


# ----------------------------------------------------------------------------- sanitising

_SECRET_KEY_RE = re.compile(
    r"pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential|admin[_-]?key", re.I
)
_REDACTED = "[redacted]"
_MAX_STR = 512
_MAX_ITEMS = 50
_MAX_DEPTH = 4


def _clean(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "...[truncated]"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_ITEMS:
                out["..."] = "[truncated]"
                break
            key = str(k)
            out[key] = _REDACTED if _SECRET_KEY_RE.search(key) else _clean(v, depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_clean(v, depth + 1) for v in list(value)[:_MAX_ITEMS]]
    return _clean(str(value), depth + 1)


def sanitize_details(details: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """JSON-safe, size-bounded copy of ``details`` with secret-looking keys redacted."""
    if details is None:
        return None
    cleaned = _clean(dict(details), 0)
    return cleaned if isinstance(cleaned, dict) else {"value": cleaned}


def url_fingerprint(url: str) -> str:
    """Stable, non-reversible id for a URL (webhook URLs can embed secrets in path/query)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def describe_url(url: str) -> dict[str, str]:
    """scheme + host + fingerprint -- never the path or query."""
    parts = urlsplit(url)
    return {"scheme": parts.scheme, "host": parts.hostname or "", "url_sha256_16": url_fingerprint(url)}


# ----------------------------------------------------------------------------- request context


def resolve_client_ip(request: Optional[Request]) -> Optional[str]:
    """Client address per the trusted-proxy rules in ``api.rate_limit.client_ip``.

    Falls back to the socket peer if that resolver cannot run (e.g. its configuration helpers are
    missing); an unparsable value is dropped rather than stored.
    """
    if request is None:
        return None
    try:
        raw = rate_limit.client_ip(request)
    except Exception:  # noqa: BLE001 - never trust headers when the proxy rules cannot be evaluated
        raw = request.client.host if request.client else None
    if not raw or raw == "unknown":
        return None
    try:
        return str(ipaddress.ip_address(raw.strip().split("%", 1)[0]))
    except ValueError:
        return None


def resolve_request_id(request: Optional[Request]) -> Optional[str]:
    """The id set by RequestIDMiddleware (same value echoed in the X-Request-ID header)."""
    current = request_id_var.get()
    if current and current != "-":
        return current[:64]
    if request is not None:
        header = request.headers.get("x-request-id")
        if header:
            return header[:64]
    return None


# ----------------------------------------------------------------------------- row construction


def _build_entry(
    *,
    action: str,
    user: Optional[User],
    resource_type: Optional[str],
    resource_id: Optional[int | str],
    details: Optional[Mapping[str, Any]],
    request: Optional[Request],
    outcome: str,
) -> AuditLog:
    if outcome not in AUDIT_OUTCOMES:
        raise ValueError(f"invalid audit outcome {outcome!r}; expected one of {AUDIT_OUTCOMES}")
    if not action or len(action) > 64:
        raise ValueError("audit action must be 1-64 characters")
    return AuditLog(
        created_at=datetime.now(timezone.utc),
        user_id=user.id if user is not None else None,
        username=user.username if user is not None else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id)[:64] if resource_id is not None else None,
        details=sanitize_details(details),
        outcome=outcome,
        request_id=resolve_request_id(request),
        client_ip=resolve_client_ip(request),
    )


# ----------------------------------------------------------------------------- atomic writer


async def log_action(
    session: AsyncSession,
    *,
    action: str,
    user: Optional[User] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int | str] = None,
    details: Optional[Mapping[str, Any]] = None,
    request: Optional[Request] = None,
    outcome: str = AUDIT_OUTCOME_SUCCESS,
) -> AuditLog:
    """Add one audit row to ``session`` and flush it (ATOMIC mode).

    The row shares the caller's transaction. Any failure raises ``AuditWriteError`` (or
    ``ValueError`` for a programming error such as a bad ``outcome``) so the action is aborted.
    ``user`` is the actor; it is denormalized (id + username) so the trail survives account deletion.
    """
    entry = _build_entry(
        action=action,
        user=user,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        request=request,
        outcome=outcome,
    )
    try:
        session.add(entry)
        await session.flush()
    except Exception as exc:
        raise AuditWriteError(f"audit write failed for {action!r}") from exc
    return entry


async def log_model_event(
    session: AsyncSession,
    *,
    action: str,
    model_name: str,
    version: str,
    outcome: str = AUDIT_OUTCOME_SUCCESS,
    user: Optional[User] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> AuditLog:
    """Atomic audit row for a model lifecycle event (promoted / rejected / quarantined).

    Roadmap 8.4: the registry ``history[]`` is written first; a failure here must make the CLI exit
    non-zero, so this raises on failure (no best-effort swallowing). The T19/T30 CLI is the caller;
    there is none in this snapshot.
    """
    if action not in MODEL_EVENT_ACTIONS:
        raise ValueError(f"{action!r} is not a model lifecycle action {MODEL_EVENT_ACTIONS}")
    return await log_action(
        session,
        action=action,
        user=user,
        resource_type="model",
        resource_id=f"{model_name}@{version}",
        details={"model": model_name, "version": version, **(dict(details) if details else {})},
        outcome=outcome,
    )


# ----------------------------------------------------------------------------- best-effort writer

_session_factory: Optional[Callable[[], AsyncSession]] = None


def set_session_factory(factory: Optional[Callable[[], AsyncSession]]) -> None:
    """Override the independent-session factory (tests); ``None`` restores ``database.AsyncSessionLocal``."""
    global _session_factory
    _session_factory = factory


def get_session_factory() -> Callable[[], AsyncSession]:
    if _session_factory is not None:
        return _session_factory
    from database import AsyncSessionLocal  # lazy: importing database creates the engine

    return AsyncSessionLocal


async def log_action_best_effort(
    *,
    action: str,
    user: Optional[User] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int | str] = None,
    details: Optional[Mapping[str, Any]] = None,
    request: Optional[Request] = None,
    outcome: str = AUDIT_OUTCOME_SUCCESS,
) -> Optional[int]:
    """Write one audit row in an independent session (BEST-EFFORT mode). Never raises.

    Returns the new row id, or ``None`` if the write failed (the failure is logged and counted in
    ``audit_write_failures_total``). Cancellation is not swallowed.
    """
    try:
        entry = _build_entry(
            action=action,
            user=user,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            request=request,
            outcome=outcome,
        )
        async with get_session_factory()() as session:
            session.add(entry)
            await session.flush()
            entry_id = entry.id
            await session.commit()
        return entry_id
    except Exception:  # noqa: BLE001 - best-effort by contract
        AUDIT_WRITE_FAILURES.inc()
        try:
            logger.warning("best-effort audit write failed for action=%s", action, exc_info=True)
        except Exception:  # noqa: BLE001
            pass
        return None


__all__ = [
    "AUDIT_OUTCOME_DENIED",
    "AUDIT_OUTCOME_FAILURE",
    "AUDIT_OUTCOME_SUCCESS",
    "AUDIT_WRITE_FAILURES",
    "AuditWriteError",
    "EVENT_MODES",
    "MODEL_EVENT_ACTIONS",
    "describe_url",
    "get_session_factory",
    "log_action",
    "log_action_best_effort",
    "log_model_event",
    "resolve_client_ip",
    "resolve_request_id",
    "sanitize_details",
    "set_session_factory",
    "url_fingerprint",
]
