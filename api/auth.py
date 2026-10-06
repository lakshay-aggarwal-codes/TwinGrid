"""
JWT authentication and role-based access for the Digital Twin API.

- POST /auth/register — create user (bcrypt hashed password). Registering
  role "operator" additionally requires the X-Admin-Key header to match the
  OPERATOR_REGISTRATION_KEY environment variable (disabled if unset).
- POST /auth/login — returns a short-lived JWT access token plus an opaque
  refresh token (see "Refresh tokens" below).
- POST /auth/refresh — exchange a valid, unrevoked refresh token for a new
  access token + refresh token (rotation: the old refresh token is revoked).
- POST /auth/logout — revoke a refresh token so it can no longer be used.
- All /api/* require a valid access token; POST /api/optimize requires role
  'operator'.

Refresh tokens
--------------
A single long-lived JWT is a standing credential: if it leaks, it's valid
for its whole lifetime with no way to revoke it. Instead, access tokens are
short-lived (``JWT_EXPIRE_MINUTES``, default 15) and a client silently
exchanges its refresh token for a new one at ``/auth/refresh`` when the
access token expires. Refresh tokens are opaque random strings (not JWTs) --
only their SHA-256 hash is stored, so a stolen database dump doesn't hand
out usable tokens -- and are stored per-user in the `refresh_tokens` table
so any individual token can be revoked (logout) without invalidating every
session, and rotate on every use: each refresh both issues a new token and
revokes the one just used, so a leaked-then-reused refresh token is
detectable (the legitimate client's next refresh will fail).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets as secrets_module
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Annotated, Optional

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.rate_limit import limiter
from api.secrets import read_secret
from api.services import audit_service
from database import get_db
from models.db_models import USER_ROLE_OPERATOR, USER_ROLE_VIEWER, RefreshToken, User

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

SECRET_KEY = read_secret("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY (or JWT_SECRET_KEY_FILE) is not set. This app will not start "
        'without it -- generate one with: python -c "import secrets; print(secrets.token_hex(32))" '
        "and set it in your .env / deployment environment, or point JWT_SECRET_KEY_FILE at a "
        "secrets-manager-mounted file. There is no default: a hardcoded fallback here would mean "
        "every deployment that forgets to set this variable shares the same, publicly-visible "
        "signing key."
    )
ALGORITHM = "HS256"
# Short-lived on purpose -- see module docstring. Was 60 minutes with no
# refresh mechanism; now a stolen access token is only useful for 15 minutes.
ACCESS_TOKEN_EXPIRE_MINUTES = int(read_secret("JWT_EXPIRE_MINUTES") or "15")
REFRESH_TOKEN_EXPIRE_DAYS = int(read_secret("REFRESH_TOKEN_EXPIRE_DAYS") or "30")

security = HTTPBearer(auto_error=True)


# -----------------------------------------------------------------------------
# Password hashing (bcrypt used directly -- passlib is unmaintained and its
# bcrypt backend breaks with bcrypt>=4.1)
# -----------------------------------------------------------------------------

_BCRYPT_MAX_BYTES = 72


def _bcrypt_input(password: str) -> bytes:
    """bcrypt only ever uses the first 72 bytes, and bcrypt>=5 raises
    ValueError for longer input -- truncate explicitly so behaviour is the
    same on every supported bcrypt version."""
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_input(plain), hashed.encode("utf-8"))
    except ValueError:
        # Malformed / non-bcrypt stored hash: treat as a failed login, not a 500.
        return False


_TRUTHY = {"1", "true", "yes", "on"}


def public_registration_enabled() -> bool:
    """Whether anyone may self-register at POST /auth/register.

    ALLOW_PUBLIC_REGISTRATION=true|false decides explicitly. If unset: OFF when
    ENVIRONMENT=production, ON otherwise (development convenience). A value that
    is set but not recognisable fails CLOSED (disabled). Read on every call, so
    no restart/reload is needed to change it.
    """
    raw = os.getenv("ALLOW_PUBLIC_REGISTRATION")
    if raw is None or not raw.strip():
        return os.getenv("ENVIRONMENT", "development").strip().lower() != "production"
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    return False  # explicit falsy, or unrecognised -> closed


def operator_registration_allowed(provided_key: Optional[str]) -> bool:
    """True only if OPERATOR_REGISTRATION_KEY is configured AND matches.

    Read from the environment on every call (not at import) so rotating the
    key needs no code change. If the variable is unset/empty, operator
    registration is disabled outright. Constant-time comparison.
    """
    expected = read_secret("OPERATOR_REGISTRATION_KEY")
    if not expected or not provided_key:
        return False
    return hmac.compare_digest(provided_key.encode("utf-8"), expected.encode("utf-8"))


# -----------------------------------------------------------------------------
# JWT
# -----------------------------------------------------------------------------


def create_access_token(subject: str | int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": str(subject), "role": role, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# -----------------------------------------------------------------------------
# Refresh tokens (opaque, hashed at rest, rotated on every use)
# -----------------------------------------------------------------------------


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_refresh_token(session: AsyncSession, user_id: int) -> str:
    """Create a new refresh token for ``user_id`` and return the plaintext.

    Only the hash is persisted -- the plaintext is returned once, to the
    caller, and never stored or logged.
    """
    plaintext = secrets_module.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash_refresh_token(plaintext),
            expires_at=expires_at,
        )
    )
    await session.flush()
    return plaintext


async def get_active_refresh_token(session: AsyncSession, plaintext: str) -> Optional[RefreshToken]:
    """Look up a refresh token by its plaintext, returning it only if it is
    still valid (not revoked, not expired). Constant-time-safe: this is a
    hash lookup, not a comparison, so there's nothing to time here."""
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh_token(plaintext))
    )
    token = result.scalar_one_or_none()
    if token is None:
        return None
    now = datetime.now(timezone.utc)
    expires_at = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=timezone.utc)
    if token.revoked_at is not None or expires_at <= now:
        return None
    return token


async def revoke_descendants_if_reused(session: AsyncSession, plaintext: str) -> bool:
    """Reuse detection. A refresh token that was already *rotated* (revoked and
    replaced by a successor) is being presented again -- either the legitimate
    client or an attacker holds a stale copy, and we can't tell which. Revoke
    every token that descends from it so neither side keeps a working session.

    Tokens revoked by /auth/logout have no successor and are NOT treated as
    reuse (replaying a logout is harmless). Returns True if a chain was revoked.
    """
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh_token(plaintext))
    )
    token = result.scalar_one_or_none()
    if token is None or token.revoked_at is None or token.replaced_by_id is None:
        return False
    now = datetime.now(timezone.utc)
    next_id, seen = token.replaced_by_id, {token.id}
    while next_id is not None and next_id not in seen:  # `seen` guards against a cycle
        seen.add(next_id)
        successor = await session.get(RefreshToken, next_id)
        if successor is None:
            break
        if successor.revoked_at is None:
            successor.revoked_at = now
        next_id = successor.replaced_by_id
    await session.flush()
    return True


async def rotate_refresh_token(session: AsyncSession, old_token: RefreshToken) -> str:
    """Revoke ``old_token`` and issue a fresh one for the same user.

    Rotation means a refresh token is single-use: replaying an intercepted
    one fails as soon as the legitimate client has used it once, which is
    the main defence an opaque, DB-backed token has over a bare long-lived
    JWT.
    """
    new_plaintext = await issue_refresh_token(session, old_token.user_id)
    new_result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh_token(new_plaintext))
    )
    new_token = new_result.scalar_one()
    old_token.revoked_at = datetime.now(timezone.utc)
    old_token.replaced_by_id = new_token.id
    await session.flush()
    return new_plaintext


async def revoke_refresh_token(session: AsyncSession, plaintext: str) -> bool:
    """Revoke a refresh token so it can no longer be used. Returns False if
    the token doesn't exist or is already revoked/expired (still a
    successful logout from the caller's point of view -- see /auth/logout)."""
    token = await get_active_refresh_token(session, plaintext)
    if token is None:
        return False
    token.revoked_at = datetime.now(timezone.utc)
    await session.flush()
    return True


async def _refresh_token_owner_id(session: AsyncSession, plaintext: str) -> Optional[int]:
    """user_id owning ``plaintext`` (even if revoked/expired), or None if unknown. Used for auditing only."""
    result = await session.execute(
        select(RefreshToken.user_id).where(RefreshToken.token_hash == _hash_refresh_token(plaintext))
    )
    return result.scalar_one_or_none()


# -----------------------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------------------


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


# -----------------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8)
    role: str = Field(default=USER_ROLE_VIEWER, pattern="^(viewer|operator)$")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str


# -----------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    session: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT and return the User. Use on all /api/* endpoints."""
    payload = decode_token(credentials.credentials)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await session.get(User, int(sub))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _audit_permission_denied(user: User, request: Optional[Request]) -> None:
    """Best-effort ``permission_denied`` audit row (roadmap 8.4) for a 403 from ``require_operator``.

    ``require_operator`` is a plain ``def`` dependency, so FastAPI runs it in a worker thread; the audit
    coroutine is handed back to the application's event loop with ``anyio.from_thread.run`` (the DB engine
    belongs to that loop). Outside a worker thread (a direct call in a unit test) or with no request there
    is nothing to hand it to and the row is skipped. Never raises and never changes the 403 decision.
    """
    if request is None:
        return
    try:
        from anyio import from_thread

        from_thread.run(
            partial(
                audit_service.log_action_best_effort,
                action="permission_denied",
                user=user,
                resource_type="endpoint",
                resource_id=f"{request.method} {request.url.path}",
                details={"required_role": "operator", "actual_role": user.role},
                request=request,
                outcome=audit_service.AUDIT_OUTCOME_DENIED,
            )
        )
    except Exception:  # noqa: BLE001 - audit is best-effort here
        audit_service.AUDIT_WRITE_FAILURES.inc()


def require_operator(
    user: Annotated[User, Depends(get_current_user)],
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI; None on direct calls
) -> User:
    """Require role 'operator'. Use on POST /api/optimize. A 403 is audited (best-effort)."""
    if not user.is_operator():
        _audit_permission_denied(user, request)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator role required to adjust controls",
        )
    return user


# -----------------------------------------------------------------------------
# Auth routes (no JWT required)
# -----------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


async def _audit_register_denied(request: Request, body: "RegisterRequest", reason: str) -> None:
    await audit_service.log_action_best_effort(
        action="permission_denied",
        resource_type="endpoint",
        resource_id="POST /auth/register",
        details={"reason": reason, "requested_role": body.role},
        request=request,
        outcome=audit_service.AUDIT_OUTCOME_DENIED,
    )


@router.post("/register", response_model=UserResponse)
@limiter.limit("5/hour")
async def register(
    request: Request,
    body: RegisterRequest,
    x_admin_key: Optional[str] = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Create a new user with hashed password. Default role: viewer. Rate limited: 5/hour per IP.

    Role "operator" requires header ``X-Admin-Key`` matching the
    OPERATOR_REGISTRATION_KEY env var (403 otherwise, and always 403 if the
    variable is unset -- operator self-registration is then disabled).

    When public registration is disabled (ALLOW_PUBLIC_REGISTRATION, see
    ``public_registration_enabled``; the default in production) this returns
    403 unless a valid ``X-Admin-Key`` is supplied -- that is how an
    administrator provisions accounts without opening sign-up to everyone.
    """
    if not public_registration_enabled() and not operator_registration_allowed(x_admin_key):
        await _audit_register_denied(request, body, "public_registration_disabled")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled",
        )
    if body.role == USER_ROLE_OPERATOR and not operator_registration_allowed(x_admin_key):
        await _audit_register_denied(request, body, "operator_key_required")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator registration requires a valid X-Admin-Key",
        )
    existing = await get_user_by_username(session, body.username)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")
    user = User(username=body.username, hashed_password=hash_password(body.password), role=body.role)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    if body.role == USER_ROLE_OPERATOR:
        # Operator accounts can trigger /api/optimize and adjust controls --
        # every one created is worth a durable record of who created it and from where.
        # Atomic (roadmap 8.4): the audit row is flushed in this same transaction; if it fails the
        # exception propagates and get_db rolls the new account back.
        await audit_service.log_action(
            session,
            action="operator_registration",
            user=user,
            resource_type="user",
            resource_id=user.id,
            details={"role": body.role, "admin_key_supplied": bool(x_admin_key)},
            request=request,
        )
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and return a short-lived access token plus a refresh
    token. Rate limited: 10/minute per IP."""
    user = await get_user_by_username(session, body.username)
    if user is None or not verify_password(body.password, user.hashed_password):
        # The attempted username is NOT stored (people paste passwords into that field); the actor is
        # recorded only when the account exists. Volume is bounded by the 10/minute per-IP limit above.
        await audit_service.log_action_best_effort(
            action="login_failure",
            user=user,
            resource_type="user",
            resource_id=user.id if user is not None else None,
            details={"reason": "invalid_credentials", "account_exists": user is not None},
            request=request,
            outcome=audit_service.AUDIT_OUTCOME_DENIED,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.id, role=user.role)
    refresh_token = await issue_refresh_token(session, user.id)
    await audit_service.log_action_best_effort(
        action="login_success",
        user=user,
        resource_type="user",
        resource_id=user.id,
        request=request,
    )
    return TokenResponse(access_token=token, refresh_token=refresh_token, role=user.role)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid, unrevoked refresh token for a new access token and
    a new refresh token (the old refresh token is revoked -- see the
    module docstring's "Refresh tokens" section)."""
    existing = await get_active_refresh_token(session, body.refresh_token)
    if existing is None:
        owner_id = await _refresh_token_owner_id(session, body.refresh_token)
        if await revoke_descendants_if_reused(session, body.refresh_token):
            # get_db rolls back when the request raises, which would undo the
            # revocation -- commit it explicitly before responding 401.
            await session.commit()
            owner = await session.get(User, owner_id) if owner_id is not None else None
            await audit_service.log_action_best_effort(
                action="refresh_reuse_detected",
                user=owner,
                resource_type="user",
                resource_id=owner_id,
                details={"descendants_revoked": True},
                request=request,
                outcome=audit_service.AUDIT_OUTCOME_DENIED,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or already-used refresh token",
        )
    user = await session.get(User, existing.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    new_refresh_token = await rotate_refresh_token(session, existing)
    access_token = create_access_token(subject=user.id, role=user.role)
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token, role=user.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def logout(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a refresh token so it can no longer be used to mint new
    access tokens. Idempotent: revoking an already-revoked/unknown token
    still returns 204, since the caller's goal (this token no longer
    works) is already true."""
    active = await get_active_refresh_token(session, body.refresh_token)
    owner = await session.get(User, active.user_id) if active is not None else None
    revoked = await revoke_refresh_token(session, body.refresh_token)
    if revoked:  # an unknown / already-revoked token is a no-op and is not an auditable logout
        await audit_service.log_action_best_effort(
            action="logout",
            user=owner,
            resource_type="user",
            resource_id=owner.id if owner is not None else None,
            request=request,
        )
