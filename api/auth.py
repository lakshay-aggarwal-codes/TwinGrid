"""
JWT authentication and role-based access for the Digital Twin API.

- POST /auth/register — create user (bcrypt hashed password). Registering
  role "operator" additionally requires the X-Admin-Key header to match the
  OPERATOR_REGISTRATION_KEY environment variable (disabled if unset).
- POST /auth/login — returns JWT token
- All /api/* require valid JWT; POST /api/optimize requires role 'operator'.
"""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.rate_limit import limiter
from database import get_db
from models.db_models import USER_ROLE_OPERATOR, USER_ROLE_VIEWER, User

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is not set. This app will not start "
        "without it -- generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and set it in your .env / deployment environment. There is no default: a "
        "hardcoded fallback here would mean every deployment that forgets to set "
        "this variable shares the same, publicly-visible signing key."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

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


def operator_registration_allowed(provided_key: Optional[str]) -> bool:
    """True only if OPERATOR_REGISTRATION_KEY is configured AND matches.

    Read from the environment on every call (not at import) so rotating the
    key needs no code change. If the variable is unset/empty, operator
    registration is disabled outright. Constant-time comparison.
    """
    expected = os.getenv("OPERATOR_REGISTRATION_KEY")
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
    token_type: str = "bearer"
    role: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


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


def require_operator(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Require role 'operator'. Use on POST /api/optimize."""
    if not user.is_operator():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator role required to adjust controls",
        )
    return user


# -----------------------------------------------------------------------------
# Auth routes (no JWT required)
# -----------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])

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
    """
    if body.role == USER_ROLE_OPERATOR and not operator_registration_allowed(x_admin_key):
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
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and return a JWT access token. Rate limited: 10/minute per IP."""
    user = await get_user_by_username(session, body.username)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.id, role=user.role)
    return TokenResponse(access_token=token, role=user.role)
