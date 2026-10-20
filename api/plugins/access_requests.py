"""Plugin: visitor access requests (Task 9, contract 8.1).

Public (no token)
* ``POST /api/access-requests``                      -- ask for a viewer account. 202, same shape for every valid body.
* ``GET  /api/access-requests/{ref}/status``         -- poll with ``X-Request-Token``; unknown ref or wrong token: one 404.
* ``POST /api/access-requests/resend-activation``    -- always 202; a new link goes out only if the request is approved.
* ``POST /api/access-requests/activate``             -- token + password -> viewer account. No session is issued.

Admin (the ``require_admin`` of ``api.plugins.admin_console``: 401 without a token, 403 + audited denial otherwise)
* ``GET  /api/admin/access-requests``, ``GET /api/admin/access-requests/{id}``
* ``POST /api/admin/access-requests/{id}/approve|reject|resend-notification|resend-activation``

Public bodies follow the contract exactly (``{"error": "..."}``), not the problem+json used elsewhere. Rate limits for the
public routes use the shared in-memory windows (``api.rate_limit``) and honour ``limiter.enabled`` / ``HTTP_LIMITS_ENABLED``.
Mail is sent after the response (background task) through ``src.notify.mail`` when that module exists.

Fail closed: ``setup`` raises when ``ENVIRONMENT=production`` and ``ACCESS_TOKEN_PEPPER`` is unset, so the plugin loader
skips this plugin (logged at ERROR) instead of serving routes that would hash tokens with a public default.
``ACCESS_REQUESTS_ENABLED=false`` makes every route here answer 404.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import config, rate_limit
from api.errors import ApiError
from api.plugins.admin_console import Admin  # imported, never edited: the existing require_admin pattern
from api.rate_limit import http_limit, limiter
from api.services import audit_service
from database import get_db
from models.db_models import ACCESS_STATUSES, AccessRequest
from src.access import rules, service, tokens

router = APIRouter(tags=["access-requests"])
Session = Annotated[AsyncSession, Depends(get_db)]

RESEND_MESSAGE = "If your request is approved, a new link has been sent."


def setup(app: Any) -> None:  # noqa: ARG001 - plugin hook
    tokens.pepper()  # raises PepperMissing in production without ACCESS_TOKEN_PEPPER -> plugin skipped


async def _enabled() -> None:
    if not rules.requests_enabled():
        raise ApiError(404, "not_found", "Not found")


Enabled = Depends(_enabled)


# ----------------------------------------------------------------------------- helpers


def _json(status_code: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, headers=headers)


def _not_found() -> JSONResponse:
    return _json(404, {"error": "not_found"})


def _iso(value: Any) -> Optional[str]:
    value = service.aware(value)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else None


def _enforce(scope: str, identity: str, count: int, window_s: int) -> None:
    """Sliding-window limit; 429 with Retry-After. Off when the shared limiter is switched off."""
    if not limiter.enabled or not config.http_limits_enabled():
        return
    retry = rate_limit._hit(f"access:{scope}", identity, count, window_s)
    if retry is not None:
        raise ApiError(
            429, "rate_limited", f"Rate limit exceeded. Retry in {retry} seconds.", headers={"Retry-After": str(retry)}
        )


async def _json_body(request: Request) -> object:
    try:
        return await request.json()
    except Exception:  # noqa: BLE001 - any unreadable body is just "not an object"
        return None


def _owner_email() -> str | None:
    return (os.getenv("ACCESS_NOTIFY_OWNER_EMAIL") or "").strip() or None


def _schedule_owner_mail(background: BackgroundTasks, row: AccessRequest) -> None:
    ctx = {"ref": row.ref, "name": row.display_name, "purpose": row.purpose or ""}
    background.add_task(service.dispatch_notification, "owner_new_request", row.id, _owner_email(), ctx)


def _schedule_activation_mail(background: BackgroundTasks, row: AccessRequest, token: str) -> None:
    url = service.activation_url(token)
    if url is None:  # production without ACCESS_PUBLIC_BASE_URL: nothing can be sent, say so
        service.mark_notify(row, service.DeliveryResult(False, "no_base_url"))
        return
    ctx = {"name": row.display_name, "activation_url": url}
    background.add_task(service.dispatch_notification, "activation", row.id, row.email_normalized, ctx)


def item_to_dict(row: AccessRequest, *, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "ref": row.ref,
        "name": row.display_name,
        "email": row.email_normalized,
        "purpose": row.purpose,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "expires_at": _iso(row.expires_at),
        "decided_at": _iso(row.decided_at),
        "decided_by": row.decided_by,
        "notify_state": row.notify_state,
        "notify_attempts": row.notify_attempts,
    }
    if detail:
        out["decision_note"] = row.decision_note
    return out


# ----------------------------------------------------------------------------- public


@router.post("/api/access-requests", status_code=202, dependencies=[Enabled])
async def submit_request(request: Request, background: BackgroundTasks, session: Session) -> JSONResponse:
    ip = audit_service.resolve_client_ip(request) or "unknown"
    _enforce("submit_ip", ip, 5, 3600)
    try:
        submission = rules.parse_submission(await _json_body(request))
    except rules.InvalidRequest:
        return _json(422, {"error": "invalid_request"})  # generic: nothing about existing accounts
    _enforce("submit_email", tokens.hash_email_for_limit(submission.email), 3, 86400)
    outcome = await service.create(session, submission, ip_hash=tokens.hash_ip(ip))
    if outcome.created and outcome.row is not None:
        _schedule_owner_mail(background, outcome.row)
    return _json(
        202,
        {
            "ref": outcome.ref,
            "status": "pending",
            "status_token": outcome.status_token,
            "expires_at": _iso(outcome.expires_at),
            "message": service.PUBLIC_RECEIVED_MESSAGE,
        },
    )


@router.get("/api/access-requests/{ref}/status", dependencies=[Enabled])
async def request_status(
    request: Request,
    session: Session,
    ref: str = Path(..., max_length=64),
    x_request_token: Annotated[Optional[str], Header(alias="X-Request-Token")] = None,
) -> JSONResponse:
    _enforce("status_ip", rate_limit.client_ip(request), 60, 60)
    view = await service.status(session, ref, x_request_token or "")
    if view is None:
        return _not_found()
    return _json(
        200,
        {
            "ref": view.ref,
            "status": view.status,
            "expires_at": _iso(view.expires_at),
            "updated_at": _iso(view.updated_at),
            "can_activate": view.can_activate,
        },
    )


@router.post("/api/access-requests/resend-activation", status_code=202, dependencies=[Enabled])
async def resend_activation_public(request: Request, background: BackgroundTasks, session: Session) -> JSONResponse:
    _enforce("resend_ip", rate_limit.client_ip(request), 3, 3600)
    body = await _json_body(request)
    ref = body.get("ref") if isinstance(body, dict) else None
    token = body.get("status_token") if isinstance(body, dict) else None
    row = await service.get_by_ref(session, ref) if isinstance(ref, str) else None
    ok = tokens.tokens_match(token if isinstance(token, str) else "", row.status_token_hash if row else None)
    if row is not None and ok and row.status == "approved" and row.activation_consumed_at is None:
        try:
            _enforce("resend_ref", row.ref, 3, 3600)  # a visitor cannot make us mail themselves in a loop
        except ApiError:
            return _json(202, {"message": RESEND_MESSAGE})  # same answer; nothing is sent
        new_token = await service.resend_activation(session, row)
        _schedule_activation_mail(background, row, new_token)
    return _json(202, {"message": RESEND_MESSAGE})


@router.post("/api/access-requests/activate", dependencies=[Enabled])
async def activate_account(request: Request, session: Session) -> JSONResponse:
    _enforce("activate_ip", rate_limit.client_ip(request), 10, 3600)
    body = await _json_body(request)
    token = body.get("token") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    try:
        await service.activate(session, token, password)
    except service.InvalidPassword as exc:
        return _json(422, {"error": "invalid_password", "reason": exc.code})
    except service.ActivationFailed as exc:
        await service.record_activation_failure(exc.code, exc.ref)
        return _json(400, {"error": "invalid_or_expired"})  # one body for every bad token
    return _json(200, {"status": "activated"})


# ----------------------------------------------------------------------------- admin


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(default=None, max_length=rules.NOTE_MAX)


def _note(body: Decision | None) -> str | None:
    try:
        return rules.clean_note(body.note if body else None)
    except rules.InvalidRequest:
        raise ApiError(422, "validation_error", "note is not acceptable") from None


def _invalid_transition() -> JSONResponse:
    return _json(409, {"error": "invalid_transition"})


async def _load(session: AsyncSession, request_id: str) -> AccessRequest:
    row = await service.get_by_id(session, request_id)
    if row is None:
        raise ApiError(404, "not_found", "Access request not found")
    await service.expire_if_due(session, row, service.utc_now())
    return row


@router.get("/api/admin/access-requests", dependencies=[Enabled, Depends(http_limit("telemetry_read"))])
async def admin_list(
    admin: Admin,
    session: Session,
    status: Optional[str] = Query(None, max_length=16),
    limit: int = Query(50, ge=1, le=100),
    before_id: Optional[str] = Query(None, max_length=36),
) -> dict[str, Any]:
    if status is not None and status not in ACCESS_STATUSES:
        raise ApiError(422, "validation_error", "unknown status")
    await service.expire_stale(session)
    stmt = select(AccessRequest)
    if status is not None:
        stmt = stmt.where(AccessRequest.status == status)
    if before_id is not None:
        anchor = await service.get_by_id(session, before_id)
        if anchor is None:
            raise ApiError(422, "validation_error", "unknown before_id")
        stmt = stmt.where(
            or_(
                AccessRequest.created_at < anchor.created_at,
                and_(AccessRequest.created_at == anchor.created_at, AccessRequest.id < anchor.id),
            )
        )
    rows = list(
        (
            await session.execute(
                stmt.order_by(AccessRequest.created_at.desc(), AccessRequest.id.desc()).limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    page = rows[:limit]
    return {
        "items": [item_to_dict(r) for r in page],
        "next_before_id": page[-1].id if len(rows) > limit and page else None,
    }


@router.get("/api/admin/access-requests/{request_id}", dependencies=[Enabled, Depends(http_limit("telemetry_read"))])
async def admin_get(admin: Admin, session: Session, request_id: str = Path(..., max_length=64)) -> dict[str, Any]:
    return item_to_dict(await _load(session, request_id), detail=True)


@router.post(
    "/api/admin/access-requests/{request_id}/approve", dependencies=[Enabled, Depends(http_limit("alert_ack"))]
)
async def admin_approve(
    admin: Admin,
    session: Session,
    background: BackgroundTasks,
    request_id: str = Path(..., max_length=64),
    body: Decision | None = None,
) -> Any:
    note = _note(body)
    try:
        row, token = await service.approve(session, request_id, admin, note)
    except service.NotFound:
        raise ApiError(404, "not_found", "Access request not found") from None
    except service.InvalidTransition:
        return _invalid_transition()
    if token is not None:
        _schedule_activation_mail(background, row, token)
    return item_to_dict(row, detail=True)


@router.post("/api/admin/access-requests/{request_id}/reject", dependencies=[Enabled, Depends(http_limit("alert_ack"))])
async def admin_reject(
    admin: Admin,
    session: Session,
    background: BackgroundTasks,
    request_id: str = Path(..., max_length=64),
    body: Decision | None = None,
) -> Any:
    note = _note(body)
    try:
        row, changed = await service.reject(session, request_id, admin, note)
    except service.NotFound:
        raise ApiError(404, "not_found", "Access request not found") from None
    except service.InvalidTransition:
        return _invalid_transition()
    if changed:  # generic, optional: the decision note is never mailed
        background.add_task(
            service.dispatch_notification, "rejected", row.id, row.email_normalized, {"name": row.display_name}
        )
    return item_to_dict(row, detail=True)


@router.post(
    "/api/admin/access-requests/{request_id}/resend-notification",
    dependencies=[Enabled, Depends(http_limit("alert_ack"))],
)
async def admin_resend_notification(
    admin: Admin, session: Session, background: BackgroundTasks, request_id: str = Path(..., max_length=64)
) -> Any:
    row = await _load(session, request_id)
    if row.status != "pending":
        return _invalid_transition()
    _schedule_owner_mail(background, row)
    return item_to_dict(row, detail=True)


@router.post(
    "/api/admin/access-requests/{request_id}/resend-activation",
    dependencies=[Enabled, Depends(http_limit("alert_ack"))],
)
async def admin_resend_activation(
    admin: Admin, session: Session, background: BackgroundTasks, request_id: str = Path(..., max_length=64)
) -> Any:
    row = await _load(session, request_id)
    try:
        token = await service.resend_activation(session, row)
    except service.InvalidTransition:
        return _invalid_transition()
    _schedule_activation_mail(background, row, token)
    return item_to_dict(row, detail=True)
