"""
Application configuration.
"""

from __future__ import annotations

import os


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
# HTTP limits (T5). Read from the environment at call time (not import time) so
# an override never needs a code change and tests can monkeypatch the env.
# Rate strings look like "30/minute" (units: second|minute|hour|day, short forms
# s/sec/m/min/h/d accepted). In-memory, per process -- see api/rate_limit.py.
# -----------------------------------------------------------------------------

# scope -> (environment variable, default)
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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None and raw.strip() else default
    except ValueError:
        return default
    return max(minimum, value)


def rate_limit_setting(scope: str) -> str:
    """Raw rate string for a limit scope (env override, else the default)."""
    env_name, default = RATE_LIMIT_DEFAULTS[scope]
    raw = os.getenv(env_name)
    return raw.strip() if raw and raw.strip() else default


def trust_proxy_headers() -> bool:
    """TRUST_PROXY_HEADERS=true: derive the client IP from X-Forwarded-For.
    Default false -- the header is ignored (it is trivially spoofable)."""
    return _env_bool("TRUST_PROXY_HEADERS", False)


def trusted_proxy_hops() -> int:
    """Number of trusted proxies in front of the app. The client IP is the
    X-Forwarded-For entry that many positions from the RIGHT (the one appended
    by the nearest trusted proxy), never the client-controlled leftmost entry."""
    return _env_int("TRUSTED_PROXY_HOPS", 1)


def max_query_string_chars() -> int:
    """Requests to limited routes with a longer raw query string get 413."""
    return _env_int("MAX_QUERY_STRING_CHARS", 16384)


# Static bound used in a Query(max_length=...) declaration (import time; 422).
MAX_RECENT_DATA_CHARS: int = _env_int("MAX_RECENT_DATA_CHARS", 4096)
