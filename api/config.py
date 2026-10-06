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


# -----------------------------------------------------------------------------
# HTTP limits (T5)
#
# scope -> (environment variable, default "<count>/<window>"). Read from the
# environment on every call so a deployment can retune without a code change
# and tests can override per test. api/rate_limit.py validates the value and
# falls back to the default here if it is malformed.
# -----------------------------------------------------------------------------

RATE_LIMIT_DEFAULTS: dict[str, tuple[str, str]] = {
    "state": ("RATE_LIMIT_STATE", "30/minute"),
    "whatif": ("RATE_LIMIT_WHATIF", "30/minute"),
    "benchmark": ("RATE_LIMIT_BENCHMARK", "30/minute"),
    "simulate": ("RATE_LIMIT_SIMULATE", "6/minute"),
    "anomaly_score": ("RATE_LIMIT_ANOMALY_SCORE", "30/minute"),
    "esg_report": ("RATE_LIMIT_ESG_REPORT", "6/minute"),
    "shadow_sample": ("RATE_LIMIT_SHADOW_SAMPLE", "10/minute"),
    "alert_ack": ("RATE_LIMIT_ALERT_ACK", "30/minute"),
    "webhook": ("RATE_LIMIT_WEBHOOK", "30/minute"),
    "optimize": ("RATE_LIMIT_OPTIMIZE", "10/minute"),
    "train_async": ("RATE_LIMIT_TRAIN_ASYNC", "5/minute"),
}

DEFAULT_MAX_QUERY_STRING_CHARS = 8192
DEFAULT_TRUSTED_PROXY_HOPS = 1
# Upper bound on the ``recent_data`` query parameter of /api/anomaly_score: a (12, 5)
# window of floats is well under 1 KB, so 8000 characters is generous.
MAX_RECENT_DATA_CHARS = 8000


def rate_limit_setting(scope: str) -> str:
    """The raw rate-limit string (e.g. ``"30/minute"``) for ``scope``: the scope's
    environment variable if set and non-blank, else its default. Unknown scope -> KeyError.
    The value is NOT validated here (see api/rate_limit.parse_rate)."""
    env_name, default = RATE_LIMIT_DEFAULTS[scope]
    raw = os.getenv(env_name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def trust_proxy_headers() -> bool:
    """True only when TRUST_PROXY_HEADERS is explicitly truthy (1/true/yes/on).
    Default False: X-Forwarded-For is client-controlled unless a trusted proxy sets it."""
    return os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes", "on"}


def trusted_proxy_hops() -> int:
    """Number of trusted proxies in front of the app (TRUSTED_PROXY_HOPS, default 1)."""
    return _env_positive_int("TRUSTED_PROXY_HOPS", DEFAULT_TRUSTED_PROXY_HOPS)


def max_query_string_chars() -> int:
    """Longest accepted raw query string (MAX_QUERY_STRING_CHARS, default 8192)."""
    return _env_positive_int("MAX_QUERY_STRING_CHARS", DEFAULT_MAX_QUERY_STRING_CHARS)
