"""
Application configuration.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

_logger = logging.getLogger(__name__)


def _parse_origins(raw: str | None) -> list[str]:
    if not raw:
        if os.getenv("ENVIRONMENT", "development").strip().lower() == "production":
            # Same reasoning as JWT_SECRET_KEY in api/auth.py: no silent
            # hardcoded fallback in production. A frontend origin baked into
            # this codebase is either stale (this deployment serves a
            # different frontend, and requests from it will be silently
            # rejected by the browser with a confusing CORS error) or, worse,
            # masks someone forgetting to set CORS_ALLOWED_ORIGINS at all.
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS is not set and ENVIRONMENT=production. Set it "
                "explicitly to a comma-separated list of allowed frontend origins, e.g.: "
                "CORS_ALLOWED_ORIGINS=https://your-frontend.example.com"
            )
        # Fallback to the one known deployed frontend rather than "*" --
        # still a single hardcoded default, but a scoped one, not a
        # wildcard. Non-production only (see above); production always
        # requires CORS_ALLOWED_ORIGINS set explicitly.
        return ["https://digital-twin-dc-conservation.lovable.app"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class Settings:
    CORS_ALLOW_ORIGINS: list[str] = _parse_origins(os.getenv("CORS_ALLOWED_ORIGINS"))
    CORS_ALLOW_CREDENTIALS: bool = True
    APP_TITLE: str = "Digital Twin API"
    APP_DESCRIPTION: str = "Data centre digital twin simulation and optimization API"
    APP_VERSION: str = "1.0.0"


settings = Settings()


# -----------------------------------------------------------------------------
# WebSocket limits (T4a)
#
# Read from the environment on every call (not at import), so a deployment can
# change them without a code change and tests can override them per test.
# -----------------------------------------------------------------------------

WS_DEFAULT_MAX_CONNECTIONS_PER_USER = 5
WS_DEFAULT_MAX_CONNECTIONS_GLOBAL = 200
WS_DEFAULT_MAX_MESSAGE_BYTES = 1024
WS_DEFAULT_MAX_MESSAGES_PER_MINUTE = 30


def _env_positive_int(name: str, default: int) -> int:
    """A positive integer from the environment. Unset -> default. A malformed or
    non-positive value also falls back to the (strict) default rather than
    disabling the limit, and says so in the log."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value <= 0:
        _logger.warning("%s=%r is not a positive integer; using default %d", name, raw, default)
        return default
    return value


def normalize_origin(origin: str) -> str:
    """Canonical form for Origin comparison: trimmed, lower-case, no trailing slash."""
    return origin.strip().rstrip("/").lower()


@dataclass(frozen=True)
class WebSocketLimits:
    max_connections_per_user: int
    max_connections_global: int
    max_message_bytes: int
    max_messages_per_minute: int
    # Empty tuple = Origin is not enforced (development default).
    allowed_origins: tuple[str, ...]


def load_ws_limits() -> WebSocketLimits:
    """WebSocket limits from the environment:

    WS_MAX_CONNECTIONS_PER_USER (default 5), WS_MAX_CONNECTIONS_GLOBAL (200),
    WS_MAX_MESSAGE_BYTES (1024), WS_MAX_MESSAGES_PER_MINUTE (30),
    WS_ALLOWED_ORIGINS (comma-separated; unset/empty = not enforced).
    """
    raw_origins = os.getenv("WS_ALLOWED_ORIGINS", "")
    origins = tuple(normalize_origin(o) for o in raw_origins.split(",") if o.strip())
    return WebSocketLimits(
        max_connections_per_user=_env_positive_int("WS_MAX_CONNECTIONS_PER_USER", WS_DEFAULT_MAX_CONNECTIONS_PER_USER),
        max_connections_global=_env_positive_int("WS_MAX_CONNECTIONS_GLOBAL", WS_DEFAULT_MAX_CONNECTIONS_GLOBAL),
        max_message_bytes=_env_positive_int("WS_MAX_MESSAGE_BYTES", WS_DEFAULT_MAX_MESSAGE_BYTES),
        max_messages_per_minute=_env_positive_int("WS_MAX_MESSAGES_PER_MINUTE", WS_DEFAULT_MAX_MESSAGES_PER_MINUTE),
        allowed_origins=origins,
    )
