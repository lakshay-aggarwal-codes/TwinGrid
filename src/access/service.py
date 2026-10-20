"""The access-request state machine (contract 8.1). Every function takes the caller's ``AsyncSession`` and works inside
that transaction (``get_db`` commits or rolls back); nothing here commits, except ``dispatch_notification`` which runs
off the request path in its own session.

States: ``pending -> approved -> activated``; terminal ``rejected`` and ``expired``.

* Idempotent: approving an approved request, rejecting a rejected one, changes nothing. Any other repeat or crossed
  transition raises ``InvalidTransition``.
* Expiry is lazy and applies to ``pending`` requests only: every read or transition first flips a pending request whose
  ``expires_at`` has passed to ``expired``. An ``approved`` request stays approved until activated; its link has its own
  TTL and can be re-issued (``resend_activation``).
* Single-use activation: the state change is a compare-and-set UPDATE, so two concurrent activations cannot both win.
* Tokens exist in plaintext only in the return value of the call that created them. The audit rows written here carry
  the request id/ref and result codes, never a token, a password or an address (``request=None`` is passed on purpose:
  the audit writer would otherwise store the client IP in clear).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import (
    ACCESS_STATUS_ACTIVATED,
    ACCESS_STATUS_APPROVED,
    ACCESS_STATUS_EXPIRED,
    ACCESS_STATUS_PENDING,
    ACCESS_STATUS_REJECTED,
    AccessRequest,
    User,
)
from src.access import rules, tokens
from src.timeutil import utc_now

logger = logging.getLogger(__name__)

ACTION_CREATED = "access_request_created"
ACTION_APPROVED = "access_request_approved"
ACTION_REJECTED = "access_request_rejected"
ACTION_EXPIRED = "access_request_expired"
ACTION_ACTIVATED = "access_request_activated"
ACTION_ACTIVATION_FAILED = "access_request_activation_failed"
ACTION_NOTIFY_FAILED = "access_request_notify_failed"
RESOURCE_TYPE = "access_request"
DECOY_RETENTION_DAYS = 30  # a decoy keeps answering ("expired") this long after its expiry

PUBLIC_RECEIVED_MESSAGE = "Your request reached TwinGrid and is awaiting the owner's decision."


class NotFound(LookupError):
    pass


class InvalidTransition(RuntimeError):
    pass


class ActivationFailed(RuntimeError):
    """Any reason an activation token cannot be used. ``code`` is for the audit row only; the client never sees it."""

    def __init__(self, code: str, ref: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.ref = ref


class InvalidPassword(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateOutcome:
    ref: str
    status_token: str
    expires_at: datetime
    row: AccessRequest | None  # None for a decoy
    created: bool  # a NEW row was stored (the owner is notified for these only)


@dataclass(frozen=True)
class StatusView:
    ref: str
    status: str
    expires_at: datetime
    updated_at: datetime
    can_activate: bool


@dataclass(frozen=True)
class DeliveryResult:
    """Same shape as ``src.notify.mail.DeliveryResult``; used when that module is absent or misbehaves."""

    ok: bool
    code: str
    backend: str = "disabled"


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything stored here is UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _audit():
    from api.services import audit_service  # lazy: api.services imports the app's models/config

    return audit_service


async def _log(
    session: AsyncSession, action: str, row: AccessRequest, *, actor: User | None = None, **details: Any
) -> None:
    await _audit().log_action(
        session,
        action=action,
        user=actor,
        resource_type=RESOURCE_TYPE,
        resource_id=row.id,
        details={"ref": row.ref, **details},
        request=None,
    )


# ----------------------------------------------------------------------------- lookups and lazy expiry


async def get_by_ref(session: AsyncSession, ref: str) -> AccessRequest | None:
    if not isinstance(ref, str) or not ref or len(ref) > 16:
        return None
    return (await session.execute(select(AccessRequest).where(AccessRequest.ref == ref))).scalar_one_or_none()


async def get_by_id(session: AsyncSession, request_id: str) -> AccessRequest | None:
    if not isinstance(request_id, str) or not request_id or len(request_id) > 36:
        return None
    return (await session.execute(select(AccessRequest).where(AccessRequest.id == request_id))).scalar_one_or_none()


async def expire_if_due(session: AsyncSession, row: AccessRequest, now: datetime) -> bool:
    """pending -> expired when ``expires_at`` has passed. True if the row changed."""
    if row.status != ACCESS_STATUS_PENDING or aware(row.expires_at) > now:  # type: ignore[operator]
        return False
    row.status = ACCESS_STATUS_EXPIRED
    row.updated_at = now
    await session.flush()
    await _log(session, ACTION_EXPIRED, row, code="ttl")
    return True


async def expire_stale(session: AsyncSession, now: datetime | None = None, limit: int = 200) -> int:
    """Flip every pending request that is past ``expires_at`` (bounded per call). Returns how many."""
    now = now or utc_now()
    stmt = (
        select(AccessRequest)
        .where(AccessRequest.status == ACCESS_STATUS_PENDING, AccessRequest.expires_at <= now)
        .order_by(AccessRequest.created_at)
        .limit(limit)
    )
    count = 0
    for row in (await session.execute(stmt)).scalars().all():
        count += int(await expire_if_due(session, row, now))
    return count


async def _compare_and_set(
    session: AsyncSession, row_id: str, expect: Mapping[str, Any], values: Mapping[str, Any]
) -> bool:
    stmt = update(AccessRequest).where(AccessRequest.id == row_id)
    for column, value in expect.items():
        col = getattr(AccessRequest, column)
        stmt = stmt.where(col.is_(None) if value is None else col == value)
    result = await session.execute(stmt.values(**values).execution_options(synchronize_session=False))
    return bool(result.rowcount == 1)  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------- create


async def create(
    session: AsyncSession, submission: rules.Submission, *, ip_hash: str, now: datetime | None = None
) -> CreateOutcome:
    """Handle a VALID submission. Same outcome shape for a new request, a duplicate pending one and a decoy."""
    now = now or utc_now()
    email = submission.email
    ttl = rules.request_ttl()

    stale = (
        (
            await session.execute(
                select(AccessRequest).where(
                    AccessRequest.email_normalized == email, AccessRequest.status == ACCESS_STATUS_PENDING
                )
            )
        )
        .scalars()
        .all()
    )
    for row in stale:
        await expire_if_due(session, row, now)

    taken = (await session.execute(select(User.id).where(User.username == email))).first() is not None
    approved = (
        await session.execute(
            select(AccessRequest.id).where(
                AccessRequest.email_normalized == email, AccessRequest.status == ACCESS_STATUS_APPROVED
            )
        )
    ).first() is not None
    if taken or approved:
        ref, token = tokens.decoy_ref_and_token(email, now)
        start = tokens.verify_decoy(ref, token, now, 1) or now
        return CreateOutcome(ref, token, start + ttl, None, False)

    pending = await _pending_for(session, email)
    if pending is not None:
        return await _rotate_status_token(session, pending, now)

    for _attempt in range(3):
        row = AccessRequest(
            ref=tokens.new_ref(),
            email_normalized=email,
            display_name=submission.name,
            purpose=submission.purpose,
            status=ACCESS_STATUS_PENDING,
            created_at=now,
            updated_at=now,
            expires_at=now + ttl,
            notify_state="pending",
            notify_attempts=0,
            request_ip_hash=ip_hash,
        )
        token = tokens.new_token()
        row.status_token_hash = tokens.hash_token(token)
        try:
            session.add(row)
            await session.flush()
        except IntegrityError:
            # Either a concurrent request for the same address won the partial unique index, or the ref collided.
            # No savepoint: roll the (so far read-only / expiry-only) transaction back and look again.
            await session.rollback()
            pending = await _pending_for(session, email)
            if pending is not None:
                return await _rotate_status_token(session, pending, now)
            continue
        await _log(session, ACTION_CREATED, row)
        return CreateOutcome(row.ref, token, aware(row.expires_at), row, True)  # type: ignore[arg-type]
    raise RuntimeError("could not allocate an access request")


async def _pending_for(session: AsyncSession, email: str) -> AccessRequest | None:
    return (
        await session.execute(
            select(AccessRequest).where(
                AccessRequest.email_normalized == email, AccessRequest.status == ACCESS_STATUS_PENDING
            )
        )
    ).scalar_one_or_none()


async def _rotate_status_token(session: AsyncSession, row: AccessRequest, now: datetime) -> CreateOutcome:
    token = tokens.new_token()
    row.status_token_hash = tokens.hash_token(token)
    row.updated_at = now
    await session.flush()
    return CreateOutcome(row.ref, token, aware(row.expires_at), row, False)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- status (public)


async def status(session: AsyncSession, ref: str, token: str, now: datetime | None = None) -> StatusView | None:
    """The visitor's view, or None (-> one identical 404) for an unknown ref OR a wrong token."""
    now = now or utc_now()
    row = await get_by_ref(session, ref)
    token_ok = tokens.tokens_match(token, row.status_token_hash if row is not None else None)
    if row is not None and token_ok:
        await expire_if_due(session, row, now)
        live_link = (
            row.status == ACCESS_STATUS_APPROVED
            and row.activation_consumed_at is None
            and row.activation_token_hash is not None
            and aware(row.activation_expires_at) is not None
            and aware(row.activation_expires_at) > now  # type: ignore[operator]
        )
        return StatusView(row.ref, row.status, aware(row.expires_at), aware(row.updated_at), live_link)  # type: ignore[arg-type]
    ttl = rules.request_ttl()
    start = tokens.verify_decoy(ref, token, now, ttl.total_seconds() / 86400 + DECOY_RETENTION_DAYS)
    if start is None:
        return None
    expires = start + ttl
    return StatusView(ref, ACCESS_STATUS_PENDING if now < expires else ACCESS_STATUS_EXPIRED, expires, start, False)


# ----------------------------------------------------------------------------- admin decisions


async def approve(
    session: AsyncSession, request_id: str, admin: User, note: str | None, now: datetime | None = None
) -> tuple[AccessRequest, str | None]:
    """pending -> approved. Returns ``(row, activation_token)``; the token is None when nothing changed (repeat approve)."""
    now = now or utc_now()
    row = await get_by_id(session, request_id)
    if row is None:
        raise NotFound(request_id)
    await expire_if_due(session, row, now)
    if row.status == ACCESS_STATUS_APPROVED:
        return row, None
    if row.status != ACCESS_STATUS_PENDING:
        raise InvalidTransition(row.status)
    token = tokens.new_token()
    won = await _compare_and_set(
        session,
        row.id,
        {"status": ACCESS_STATUS_PENDING},
        {
            "status": ACCESS_STATUS_APPROVED,
            "decided_at": now,
            "decided_by": admin.id,
            "decision_note": note,
            "activation_token_hash": tokens.hash_token(token),
            "activation_expires_at": now + rules.activation_ttl(),
            "activation_consumed_at": None,
            "updated_at": now,
        },
    )
    await session.refresh(row)
    if not won:
        if row.status == ACCESS_STATUS_APPROVED:
            return row, None
        raise InvalidTransition(row.status)
    await _log(session, ACTION_APPROVED, row, actor=admin, note_present=bool(note))
    return row, token


async def reject(
    session: AsyncSession, request_id: str, admin: User, note: str | None, now: datetime | None = None
) -> tuple[AccessRequest, bool]:
    """pending -> rejected. Returns ``(row, changed)``."""
    now = now or utc_now()
    row = await get_by_id(session, request_id)
    if row is None:
        raise NotFound(request_id)
    await expire_if_due(session, row, now)
    if row.status == ACCESS_STATUS_REJECTED:
        return row, False
    if row.status != ACCESS_STATUS_PENDING:
        raise InvalidTransition(row.status)
    won = await _compare_and_set(
        session,
        row.id,
        {"status": ACCESS_STATUS_PENDING},
        {
            "status": ACCESS_STATUS_REJECTED,
            "decided_at": now,
            "decided_by": admin.id,
            "decision_note": note,
            "updated_at": now,
        },
    )
    await session.refresh(row)
    if not won:
        if row.status == ACCESS_STATUS_REJECTED:
            return row, False
        raise InvalidTransition(row.status)
    await _log(session, ACTION_REJECTED, row, actor=admin, note_present=bool(note))
    return row, True


async def resend_activation(session: AsyncSession, row: AccessRequest, now: datetime | None = None) -> str:
    """Rotate the activation token of an ``approved`` request (the old link stops working). Returns the new token."""
    now = now or utc_now()
    if row.status != ACCESS_STATUS_APPROVED or row.activation_consumed_at is not None:
        raise InvalidTransition(row.status)
    token = tokens.new_token()
    row.activation_token_hash = tokens.hash_token(token)
    row.activation_expires_at = now + rules.activation_ttl()
    row.updated_at = now
    await session.flush()
    return token


# ----------------------------------------------------------------------------- activation (public)


async def activate(session: AsyncSession, token: object, password: object, now: datetime | None = None) -> User:
    """Consume an activation token and create the viewer account. No session or JWT is issued.

    Raises ``InvalidPassword`` (policy; the token is NOT consumed) or ``ActivationFailed`` (one client-visible outcome for
    every bad token). The password length is checked before the token lookup, so that check reveals nothing about tokens.
    """
    now = now or utc_now()
    if rules.password_problem(password) == "length":
        raise InvalidPassword("length")
    if not isinstance(token, str) or len(token) != tokens.TOKEN_LEN:
        raise ActivationFailed("malformed")
    digest = tokens.hash_token(token)
    row = (
        await session.execute(select(AccessRequest).where(AccessRequest.activation_token_hash == digest))
    ).scalar_one_or_none()
    if row is None or not tokens.tokens_match(token, row.activation_token_hash):
        raise ActivationFailed("unknown")
    if row.status != ACCESS_STATUS_APPROVED or row.activation_consumed_at is not None:
        raise ActivationFailed("not_usable", row.ref)
    expiry = aware(row.activation_expires_at)
    if expiry is None or expiry <= now:
        raise ActivationFailed("expired", row.ref)
    problem = rules.password_problem(password, row.email_normalized)
    if problem is not None:
        raise InvalidPassword(problem)

    ref = row.ref  # read now: a rollback below expires the instance
    from api import auth  # lazy: api.auth needs JWT_SECRET_KEY at import

    hashed = await asyncio.to_thread(auth.hash_password, str(password))  # bcrypt is CPU-bound; keep it off the loop
    try:
        won = await _compare_and_set(
            session,
            row.id,
            {"status": ACCESS_STATUS_APPROVED, "activation_consumed_at": None, "activation_token_hash": digest},
            {
                "status": ACCESS_STATUS_ACTIVATED,
                "activation_consumed_at": now,
                "activation_token_hash": None,
                "updated_at": now,
            },
        )
        if not won:
            raise ActivationFailed("replayed", row.ref)
        user = User(username=row.email_normalized, hashed_password=hashed, role="viewer")
        session.add(user)
        await session.flush()
        await session.execute(
            update(AccessRequest)
            .where(AccessRequest.id == row.id)
            .values(user_id=user.id)
            .execution_options(synchronize_session=False)
        )
    except ActivationFailed:
        await (
            session.rollback()
        )  # the compare-and-set may have matched nothing, but leave no half-applied state either way
        raise
    except IntegrityError:
        await session.rollback()  # the account name is taken: undo the consume as well, nothing is half-applied
        raise ActivationFailed("account_exists", ref) from None
    await session.refresh(row)
    # no actor: the new account's username IS the visitor's address, which audit rows must not carry
    await _log(session, ACTION_ACTIVATED, row, user_id=user.id)
    return user


async def record_activation_failure(code: str, ref: str | None) -> None:
    """Best-effort (independent session): survives the request's own rollback. Never carries the token."""
    await _audit().log_action_best_effort(
        action=ACTION_ACTIVATION_FAILED,
        resource_type=RESOURCE_TYPE,
        resource_id=ref,
        details={"code": rules.safe_code(code), **({"ref": ref} if ref else {})},
        outcome=_audit().AUDIT_OUTCOME_FAILURE,
    )


# ----------------------------------------------------------------------------- notification bookkeeping and mail hook


def mark_notify(row: AccessRequest, result: Any) -> str:
    """Record one delivery attempt on ``row``. Returns the stored ``notify_state``. Only a short code is kept."""
    code = rules.safe_code(getattr(result, "code", None))
    if getattr(result, "ok", False) is True:
        state = "sent"
    elif code in {"not_configured", "mail_unavailable", "no_owner_email", "no_base_url"}:
        state = "not_configured"
    else:
        state = "failed"
    row.notify_state = state
    row.notify_attempts = int(row.notify_attempts or 0) + 1
    row.notify_last_code = code if state != "sent" else "ok"
    return state


def _mail_timeout() -> float:
    try:
        return max(1.0, float(os.getenv("ACCESS_NOTIFY_TIMEOUT_S", "10"))) + 5.0
    except ValueError:
        return 15.0


async def deliver(kind: str, to: str | None, ctx: Mapping[str, str]) -> Any:
    """Call ``src.notify.mail.send_access_mail`` if it exists. Never raises; the result has ``ok`` and ``code``."""
    if not to:
        return DeliveryResult(False, "no_owner_email" if kind == "owner_new_request" else "invalid_recipient")
    try:
        from src.notify import mail  # Task 10; imported lazily so this task works without it
    except ImportError:
        return DeliveryResult(False, "mail_unavailable")
    try:
        return await asyncio.wait_for(mail.send_access_mail(kind, to, dict(ctx)), timeout=_mail_timeout())  # type: ignore[arg-type]
    except asyncio.TimeoutError:
        return DeliveryResult(False, "timeout", "smtp")
    except Exception:  # noqa: BLE001 - the class name only goes to the log, never the message
        logger.warning("access mail adapter raised")
        return DeliveryResult(False, "error")


def public_base_url() -> str | None:
    raw = os.getenv("ACCESS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if raw:
        return raw
    return None if os.getenv("ENVIRONMENT", "development").strip().lower() == "production" else "http://localhost:5173"


def activation_url(token: str) -> str | None:
    base = public_base_url()
    return f"{base}/activate#token={token}" if base else None


async def dispatch_notification(kind: str, request_id: str, to: str | None, ctx: Mapping[str, str]) -> None:
    """Send one access mail and record the outcome. Runs AFTER the response (background task), in its own session, so
    SMTP latency never blocks a request. Never raises."""
    try:
        result = await deliver(kind, to, ctx)
        factory = _audit().get_session_factory()
        async with factory() as session:
            row = await get_by_id(session, request_id)
            if row is None:  # the request's own transaction may not have committed yet: one short retry
                await asyncio.sleep(0.25)
                row = await get_by_id(session, request_id)
            if row is None:
                return
            state = mark_notify(row, result)
            code = row.notify_last_code
            ref = row.ref
            await session.commit()
        if state == "failed":
            await _audit().log_action_best_effort(
                action=ACTION_NOTIFY_FAILED,
                resource_type=RESOURCE_TYPE,
                resource_id=request_id,
                details={"ref": ref, "kind": kind, "code": code},
                outcome=_audit().AUDIT_OUTCOME_FAILURE,
            )
    except Exception:  # noqa: BLE001
        logger.warning("access notification bookkeeping failed (kind=%s)", kind)
