"""Plugin: the admin console (Task 29). Every route here is admin-only.

Users and roles
* ``GET  /api/admin/users``                  -- accounts (no password hashes) and role counts.
* ``POST /api/admin/users/{id}/role``        -- set a role (viewer, operator, admin). Not on yourself, never removing the
  last admin. Roles are read from the database on every request, so a change applies at once.

Audit log
* ``GET  /api/admin/audit``                  -- filtered, newest first, paged by ``before_id`` (``api/services/audit_service``).
* ``GET  /api/admin/audit/export``           -- the same filters as CSV or JSON, bounded to ``EXPORT_MAX_ROWS`` rows;
  CSV cells are neutralised against formula injection. Each export is itself audited (``audit_exported``).

Webhooks (the existing file registry and ``webhook_service``)
* ``GET|POST /api/admin/webhooks``, ``PUT|DELETE /api/admin/webhooks/{id}``, ``POST /api/admin/webhooks/{id}/test``,
  ``GET /api/admin/webhooks/deliveries``. A webhook is shown only as id, scheme, host and port: the path and query can
  hold secret tokens and are never returned. The delivery log is a bounded file (``src/webhook_deliveries.py``).

System
* ``GET  /api/admin/system``                 -- readiness components (the ``/readyz`` logic), versions, migration head vs
  database revision, uptime, model state and registry, and where the API docs are. Statuses and counts only: no paths,
  environment values, connection strings or exception text; a part that cannot be read is reported as unavailable.

Audit: every write is one atomic row, flushed BEFORE any non-transactional effect (``user_role_changed``,
``webhook_registered``, ``webhook_updated``, ``webhook_unregistered``, ``webhook_test_fired``, ``audit_exported``; not added to
``audit_service.EVENT_MODES``, which a test pins). A non-admin gets 403 and a best-effort ``permission_denied`` row.
Rate limits reuse ``telemetry_read`` (reads), ``alert_ack`` (role changes) and ``webhook`` (webhook writes and test-fires).
"""

from __future__ import annotations

import asyncio
import json
import platform
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.config import settings
from api.errors import ApiError
from api.rate_limit import http_limit
from api.serialization import to_jsonable
from api.services import audit_service, webhook_service
from api.services.webhook_security import WebhookURLError, validate_webhook_url
from database import get_db
from models.db_models import User
from src import model_registry, versions, webhook_deliveries, webhook_registry
from src.admin_console import rules

router = APIRouter(tags=["admin"])

# "Uptime" is measured from when this module was imported, i.e. when the app loaded its plugins.
_STARTED_AT = datetime.now(timezone.utc)
_STARTED_MONO = time.monotonic()

MAX_URL_CHARS = 2048
DELIVERIES_MAX = 200


# ----------------------------------------------------------------------------- roles


async def _deny(user: User, request: Request) -> None:
    await audit_service.log_action_best_effort(
        action="permission_denied",
        user=user,
        resource_type="endpoint",
        resource_id=f"{request.method} {request.url.path}",
        details={"required_role": "admin", "actual_role": user.role},
        request=request,
        outcome=audit_service.AUDIT_OUTCOME_DENIED,
    )
    raise ApiError(403, "forbidden", "Admin role required")


async def require_admin(request: Request, user: Annotated[User, Depends(get_current_user)]) -> User:
    if not rules.can_administer(user.role):
        await _deny(user, request)
    return user


Admin = Annotated[User, Depends(require_admin)]
Session = Annotated[AsyncSession, Depends(get_db)]


# ----------------------------------------------------------------------------- users


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def user_to_dict(u: User, viewer_id: Optional[int] = None) -> dict[str, Any]:
    """Never includes the password hash."""
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "created_at": _iso(u.created_at),
        "is_you": u.id == viewer_id,
    }


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["viewer", "operator", "admin"]


@router.get("/api/admin/users", dependencies=[Depends(http_limit("telemetry_read"))])
async def list_users(admin: Admin, session: Session) -> dict[str, Any]:
    rows = list((await session.execute(select(User).order_by(User.id).limit(rules.USERS_MAX + 1))).scalars().all())
    counts = {role: 0 for role in rules.ROLES}
    for u in rows[: rules.USERS_MAX]:
        if u.role in counts:
            counts[u.role] += 1
    return to_jsonable(
        {
            "users": [user_to_dict(u, admin.id) for u in rows[: rules.USERS_MAX]],
            "truncated": len(rows) > rules.USERS_MAX,
            "roles": list(rules.ROLES),
            "counts": counts,
        }
    )


@router.post("/api/admin/users/{user_id}/role", dependencies=[Depends(http_limit("alert_ack"))])
async def change_role(
    request: Request, admin: Admin, session: Session, body: RoleChange, user_id: int = Path(..., ge=1)
) -> dict[str, Any]:
    target = await session.get(User, user_id)
    if target is None:
        raise ApiError(404, "not_found", "User not found")
    count_stmt = select(func.count()).select_from(User).where(User.role == "admin")
    admin_count = (await session.execute(count_stmt)).scalar_one()
    code = rules.check_role_change(
        actor_id=admin.id,
        target_id=target.id,
        current_role=target.role,
        new_role=body.role,
        admin_count=int(admin_count),
    )
    if code is not None:
        raise ApiError(409, code, rules.ROLE_CHANGE_MESSAGES[code])
    previous = target.role
    target.role = body.role
    await audit_service.log_action(
        session,
        action="user_role_changed",
        user=admin,
        resource_type="user",
        resource_id=target.id,
        details={"username": target.username, "from": previous, "to": body.role},
        request=request,
    )
    return to_jsonable(user_to_dict(target, admin.id))


# ----------------------------------------------------------------------------- audit log


def _filters(
    action: Optional[str],
    outcome: Optional[str],
    username: Optional[str],
    resource_type: Optional[str],
    since: Optional[datetime],
    until: Optional[datetime],
    before_id: Optional[int] = None,
) -> rules.AuditFilters:
    try:
        return rules.parse_filters(
            action=action,
            outcome=outcome,
            username=username,
            resource_type=resource_type,
            since=since,
            until=until,
            before_id=before_id,
        )
    except rules.FilterError as exc:  # our own messages
        raise ApiError(422, "invalid_filter", str(exc)) from exc


@router.get("/api/admin/audit", dependencies=[Depends(http_limit("telemetry_read"))])
async def audit_log(
    admin: Admin,
    session: Session,
    action: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    outcome: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    username: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    resource_type: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    before_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(rules.AUDIT_PAGE_DEFAULT, ge=1, le=rules.AUDIT_PAGE_MAX),
) -> dict[str, Any]:
    f = _filters(action, outcome, username, resource_type, since, until, before_id)
    rows, has_more = await audit_service.query_logs(session, f, limit)
    items = [audit_service.row_to_dict(r) for r in rows]
    return to_jsonable(
        {
            "items": items,
            "has_more": has_more,
            "next_before_id": items[-1]["id"] if has_more and items else None,
            "limit": limit,
            "actions": await audit_service.list_actions(session),
            "outcomes": list(rules.OUTCOMES),
        }
    )


@router.get("/api/admin/audit/export", dependencies=[Depends(http_limit("telemetry_read"))])
async def audit_export(
    request: Request,
    admin: Admin,
    session: Session,
    format: Literal["csv", "json"] = Query("csv"),
    action: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    outcome: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    username: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    resource_type: Optional[str] = Query(None, max_length=rules.MAX_FILTER_CHARS),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
) -> Response:
    """At most ``EXPORT_MAX_ROWS`` newest matching rows (``X-Export-Truncated: true`` says when there were more)."""
    f = _filters(action, outcome, username, resource_type, since, until)
    rows, truncated = await audit_service.query_logs(session, f, rules.EXPORT_MAX_ROWS)
    dicts = [audit_service.row_to_dict(r) for r in rows]
    # Audit first (atomic): if the row cannot be written, nothing is handed out.
    await audit_service.log_action(
        session,
        action="audit_exported",
        user=admin,
        resource_type="audit_log",
        details={"format": format, "rows": len(dicts), "truncated": truncated, "filters": f.as_details()},
        request=request,
    )
    body = rules.to_csv(dicts) if format == "csv" else rules.to_json(dicts)
    filename = rules.export_filename(datetime.now(timezone.utc), format)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8" if format == "csv" else "application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Truncated": "true" if truncated else "false",
            "X-Export-Rows": str(len(dicts)),
            "Cache-Control": "no-store",
        },
    )


# ----------------------------------------------------------------------------- webhooks


class WebhookBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=1, max_length=MAX_URL_CHARS)


async def _validated(url: str) -> str:
    try:
        # DNS lookup blocks, so keep it off the event loop.
        await run_in_threadpool(validate_webhook_url, url)
    except WebhookURLError as exc:  # our own messages
        raise ApiError(422, "invalid_webhook_url", str(exc)) from exc
    return url


def _registered(wid: str) -> str:
    url = rules.find_webhook(webhook_registry.list_subscribers(), wid)
    if url is None:
        raise ApiError(404, "not_found", "Webhook not found")
    return url


def _listing() -> dict[str, Any]:
    last: dict[str, dict[str, Any]] = {}
    for rec in webhook_deliveries.recent(webhook_deliveries.MAX_RECORDS):
        last.setdefault(str(rec.get("webhook_id")), rec)  # newest first, so the first seen is the latest
    hooks = []
    for url in webhook_registry.list_subscribers():
        view = rules.webhook_view(url)
        view["last_delivery"] = last.get(view["id"])
        hooks.append(view)
    return {
        "webhooks": hooks,
        "max": webhook_registry.MAX_SUBSCRIBERS,
        "fires_for_simulated_alerts": webhook_service.webhook_on_simulated(),
    }


@router.get("/api/admin/webhooks", dependencies=[Depends(http_limit("telemetry_read"))])
async def list_webhooks(admin: Admin) -> dict[str, Any]:
    return to_jsonable(await run_in_threadpool(_listing))


@router.get("/api/admin/webhooks/deliveries", dependencies=[Depends(http_limit("telemetry_read"))])
async def webhook_deliveries_log(
    admin: Admin,
    webhook_id: Optional[str] = Query(None, min_length=16, max_length=16, pattern="^[0-9a-f]{16}$"),
    limit: int = Query(50, ge=1, le=DELIVERIES_MAX),
) -> dict[str, Any]:
    records = await run_in_threadpool(webhook_deliveries.recent, limit, webhook_id)
    return to_jsonable(
        {
            "deliveries": records,
            "note": "Recent attempts, newest first, kept in a bounded file. With several API workers it is partial.",
        }
    )


@router.post("/api/admin/webhooks", dependencies=[Depends(http_limit("webhook"))])
async def create_webhook(request: Request, admin: Admin, session: Session, body: WebhookBody) -> dict[str, Any]:
    url = await _validated(body.url)
    if rules.find_webhook(webhook_registry.list_subscribers(), rules.webhook_id(url)) is not None:
        raise ApiError(409, "already_registered", "That webhook is already registered")
    if len(webhook_registry.list_subscribers()) >= webhook_registry.MAX_SUBSCRIBERS:
        raise ApiError(
            409, "subscriber_limit", f"At most {webhook_registry.MAX_SUBSCRIBERS} webhook subscribers are allowed"
        )
    await audit_service.log_action(
        session,
        action="webhook_registered",
        user=admin,
        resource_type="webhook",
        resource_id=audit_service.url_fingerprint(url),
        details=audit_service.describe_url(url),
        request=request,
    )
    try:
        webhook_registry.register(url)
    except webhook_registry.SubscriberLimitError as exc:
        raise ApiError(409, "subscriber_limit", str(exc)) from exc
    return to_jsonable(await run_in_threadpool(_listing))


@router.put("/api/admin/webhooks/{wid}", dependencies=[Depends(http_limit("webhook"))])
async def replace_webhook(
    request: Request, admin: Admin, session: Session, body: WebhookBody, wid: str = Path(..., pattern="^[0-9a-f]{16}$")
) -> dict[str, Any]:
    old = _registered(wid)
    new = await _validated(body.url)
    if new == old:
        raise ApiError(409, "unchanged", "That is already this webhook's URL")
    if rules.find_webhook(webhook_registry.list_subscribers(), rules.webhook_id(new)) is not None:
        raise ApiError(409, "already_registered", "That webhook is already registered")
    await audit_service.log_action(
        session,
        action="webhook_updated",
        user=admin,
        resource_type="webhook",
        resource_id=wid,
        details={"from": rules.webhook_id(old), "to": audit_service.describe_url(new)},
        request=request,
    )
    try:
        webhook_registry.replace(old, new)
    except KeyError as exc:
        raise ApiError(404, "not_found", "Webhook not found") from exc
    except ValueError as exc:
        raise ApiError(409, "already_registered", "That webhook is already registered") from exc
    return to_jsonable(await run_in_threadpool(_listing))


@router.delete("/api/admin/webhooks/{wid}", dependencies=[Depends(http_limit("webhook"))])
async def delete_webhook(
    request: Request, admin: Admin, session: Session, wid: str = Path(..., pattern="^[0-9a-f]{16}$")
) -> dict[str, Any]:
    url = _registered(wid)
    await audit_service.log_action(
        session,
        action="webhook_unregistered",
        user=admin,
        resource_type="webhook",
        resource_id=wid,
        details=audit_service.describe_url(url),
        request=request,
    )
    webhook_registry.unregister(url)
    return to_jsonable(await run_in_threadpool(_listing))


@router.post("/api/admin/webhooks/{wid}/test", dependencies=[Depends(http_limit("webhook"))])
async def fire_test_webhook(
    request: Request, admin: Admin, session: Session, wid: str = Path(..., pattern="^[0-9a-f]{16}$")
) -> dict[str, Any]:
    """Send one clearly-labelled test event. A subscriber that fails is a RESULT (``ok: false``), not an API error."""
    url = _registered(wid)
    await audit_service.log_action(
        session,
        action="webhook_test_fired",
        user=admin,
        resource_type="webhook",
        resource_id=wid,
        details=audit_service.describe_url(url),
        request=request,
    )
    result = await asyncio.to_thread(webhook_service.send_test, url)
    return to_jsonable(
        {
            "webhook_id": wid,
            "ok": result.ok,
            "status_code": result.status_code,
            "error_kind": result.error_kind,
            "duration_ms": result.duration_ms,
        }
    )


# ----------------------------------------------------------------------------- system status


def _registry_summary() -> Optional[list[dict[str, Any]]]:
    try:
        entries = model_registry.read_registry()
    except (OSError, ValueError):
        return None
    out = []
    for e in entries[-50:]:
        row = {k: e.get(k) for k in ("name", "kind", "version", "status", "created_at_utc", "physics_version")}
        out.append({k: (v if isinstance(v, (str, int, float)) or v is None else str(v)) for k, v in row.items()})
    return out


@router.get("/api/admin/system", dependencies=[Depends(http_limit("telemetry_read"))])
async def system_status(admin: Admin, session: Session) -> dict[str, Any]:
    from api.routes import health_routes  # reused, not copied: the console shows the same answer /readyz gives

    unavailable: list[str] = []
    readiness: Optional[dict[str, Any]] = None
    try:
        resp = await health_routes.readiness(session)
        readiness = json.loads(resp.body)
    except Exception:  # noqa: BLE001 - a status page must not fail because one probe did
        unavailable.append("readiness")

    migration: Optional[dict[str, Any]] = None
    try:
        head = health_routes._alembic_head()
        current = await health_routes._database_revision(session)
        migration = {"head": head, "database": current, "at_head": head is not None and head == current}
    except Exception:  # noqa: BLE001
        unavailable.append("migration")

    try:
        physics: Optional[str] = versions.active_physics_version()
    except Exception:  # noqa: BLE001
        physics = None
        unavailable.append("physics_version")

    registry = _registry_summary()
    if registry is None:
        unavailable.append("model_registry")

    return to_jsonable(
        {
            "readiness": readiness,
            "migration": migration,
            "versions": {
                "app": settings.APP_VERSION,
                "title": settings.APP_TITLE,
                "physics": physics,
                "safety_envelope": versions.SAFETY_ENVELOPE_VERSION,
                "python": platform.python_version(),
            },
            "uptime": {
                "started_at": _iso(_STARTED_AT),
                "seconds": int(time.monotonic() - _STARTED_MONO),
                "basis": "since this process loaded the API plugins",
            },
            "models": {
                "state": (readiness or {}).get("components"),
                "registry": registry,
            },
            "docs": {"swagger": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"},
            "unavailable": unavailable,
        }
    )
