"""
Application configuration.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from api.startup_checks import StartupConfigError

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
            raise StartupConfigError(
                ["CORS_ALLOWED_ORIGINS"],
                "CORS_ALLOWED_ORIGINS is not set and ENVIRONMENT=production. Set it explicitly to a "
                "comma-separated list of allowed frontend origins, e.g. https://your-frontend.example.com",
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
# Time contract (T12, roadmap §9.2) -- see docs/TIME_POLICY.md
#
# SITE_TIMEZONE: IANA zone used for wall-clock/diurnal logic (hour-of-day) via
#   src.timeutil.to_site_local. Persisted instants are always aware UTC.
# SIM_STEP_SECONDS: nominal simulated seconds per twin step (A-1). Declared
#   here as the single configured value; the physics step itself is not driven
#   by it in T12 (physics numerics are out of scope) -- a test pins it to
#   src.digital_twin.INTERVAL_MINUTES * 60.
# -----------------------------------------------------------------------------
from src.timeutil import DEFAULT_SITE_TIMEZONE, site_timezone_name  # noqa: E402, F401  (re-exported)

DEFAULT_SIM_STEP_SECONDS = 300
SITE_TIMEZONE: str = site_timezone_name()  # import-time snapshot; timeutil re-reads the env per call


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
# HTTP rate limits and request-size cap (T5; consumed by api/rate_limit.py)
#
# All values are read from the environment on every call (not at import), so a
# deployment or a test can change them without a reload.
# -----------------------------------------------------------------------------

# scope -> (environment variable name, default "<count>/<unit>")
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
    # T14: applied (at include_router level, see api/main.py) to every route that has no scope of its own.
    "general": ("RATE_LIMIT_GENERAL", "120/minute"),
    # T17: GET /api/telemetry/... (samples and gaps share one bucket per client).
    "telemetry_read": ("RATE_LIMIT_TELEMETRY_READ", "60/minute"),
}

# Paths never rate limited (infrastructure probes). /healthz is today's liveness route; /livez is its planned name.
HTTP_LIMIT_EXEMPT_PATHS: frozenset[str] = frozenset({"/livez", "/healthz"})

DEFAULT_TRUSTED_PROXY_HOPS = 1
DEFAULT_MAX_QUERY_STRING_CHARS = 8192

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def rate_limit_setting(scope: str) -> str:
    """The raw ``"<count>/<unit>"`` limit for ``scope``: its env var if set and non-blank, else the default.

    Raises KeyError for an unknown scope. The value is NOT validated here; api/rate_limit.py
    parses it and falls back to the default (with a warning) when it is malformed.
    """
    env_name, default = RATE_LIMIT_DEFAULTS[scope]
    raw = os.getenv(env_name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def trust_proxy_headers() -> bool:
    """TRUST_PROXY_HEADERS: honour X-Forwarded-For. Off unless explicitly enabled (true/1/yes/on)."""
    return os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in _TRUE_VALUES


def trusted_proxy_hops() -> int:
    """TRUSTED_PROXY_HOPS (default 1): how many right-most X-Forwarded-For entries were added by trusted proxies."""
    return _env_positive_int("TRUSTED_PROXY_HOPS", DEFAULT_TRUSTED_PROXY_HOPS)


def max_query_string_chars() -> int:
    """MAX_QUERY_STRING_CHARS (default 8192): longest query string accepted before 413."""
    return _env_positive_int("MAX_QUERY_STRING_CHARS", DEFAULT_MAX_QUERY_STRING_CHARS)


def sim_step_seconds() -> int:
    """Configured simulated seconds per step (env ``SIM_STEP_SECONDS``, default 300)."""
    return _env_positive_int("SIM_STEP_SECONDS", DEFAULT_SIM_STEP_SECONDS)


SIM_STEP_SECONDS: int = sim_step_seconds()


# -----------------------------------------------------------------------------
# Cost controls (T14). Read on every call, like the limits above.
# -----------------------------------------------------------------------------

# Upper bound on the ``recent_data`` query parameter of /api/anomaly_score (a 12 x 5 window is ~1.2 kB).
MAX_RECENT_DATA_CHARS = 4096
# /api/simulate?persist=true writes one run + one reading per simulated hour; hours is validated <= 168.
MAX_SIMULATE_PERSIST_ROWS = 168

DEFAULT_MAX_BODY_BYTES = 1024 * 1024  # 1 MiB
DEFAULT_COMPUTE_TIMEOUT_S = 60.0
DEFAULT_MAX_CONCURRENT_COMPUTE = 4


def _env_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        value = 0.0
    if not value > 0 or value == float("inf"):
        _logger.warning("%s=%r is not a positive number; using default %s", name, raw, default)
        return default
    return value


def http_limits_enabled() -> bool:
    """HTTP_LIMITS_ENABLED (default true). ``false``/``0``/``no``/``off`` switches the per-client request-rate
    windows off (rollback switch). The query-string cap, body cap, timeout and concurrency bound stay on."""
    return os.getenv("HTTP_LIMITS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def max_body_bytes() -> int:
    """MAX_BODY_BYTES (default 1 MiB): larger request bodies are rejected with 413."""
    return _env_positive_int("MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)


def compute_timeout_s() -> float:
    """COMPUTE_TIMEOUT_S (default 60): wall-clock budget of one compute-heavy request; exceeded -> 504."""
    return _env_positive_float("COMPUTE_TIMEOUT_S", DEFAULT_COMPUTE_TIMEOUT_S)


def max_concurrent_compute() -> int:
    """MAX_CONCURRENT_COMPUTE (default 4): compute-heavy requests in flight per process; more -> 429."""
    return _env_positive_int("MAX_CONCURRENT_COMPUTE", DEFAULT_MAX_CONCURRENT_COMPUTE)


# -----------------------------------------------------------------------------
# Telemetry (T17). Read on every call so a deployment or a test can change them without a reload.
# -----------------------------------------------------------------------------

# The anomaly model's input cadence. A constant until T19 moves it into the model manifest (``input_cadence_s``).
ANOMALY_INPUT_CADENCE_S = 300

DEFAULT_MQTT_QUEUE_MAX = 10_000
DEFAULT_TELEMETRY_MAX_SPAN_H = 168
TELEMETRY_WINDOW_SOURCES = ("store", "memory")

# The five anomaly features (api.services.telemetry_window.FEATURE_ORDER) -- all direct measurands.
TELEMETRY_FEATURES: tuple[str, ...] = (
    "water_flow_lpm",
    "water_pressure_bar",
    "server_outlet_temp_C",
    "it_power_kw",
    "humidity_pct",
)


def telemetry_store_enabled() -> bool:
    """TELEMETRY_STORE_ENABLED (default true). ``false`` is the rollback switch: producers write the legacy
    ``sensor_readings`` table only and nothing is written to ``telemetry_sample``."""
    return os.getenv("TELEMETRY_STORE_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def telemetry_window_source() -> str:
    """TELEMETRY_WINDOW_SOURCE: ``store`` (default; window built from stored samples) or ``memory`` (rollback: the
    in-process ring buffer). Anything else falls back to ``store`` with a warning, never to the weaker source."""
    raw = os.getenv("TELEMETRY_WINDOW_SOURCE", "store").strip().lower()
    if raw in TELEMETRY_WINDOW_SOURCES:
        return raw
    _logger.warning("TELEMETRY_WINDOW_SOURCE=%r is not one of %s; using 'store'", raw, TELEMETRY_WINDOW_SOURCES)
    return "store"


def telemetry_max_span_h() -> int:
    """TELEMETRY_MAX_SPAN_H (default 168): longest ``to - from`` the read API accepts."""
    return _env_positive_int("TELEMETRY_MAX_SPAN_H", DEFAULT_TELEMETRY_MAX_SPAN_H)


def telemetry_facility_id() -> int:
    """TELEMETRY_FACILITY_ID (default 1): the facility whose facility-level sensors feed the anomaly window
    (``fac<id>.<measurand>``, see scripts/seed_facility.py)."""
    return _env_positive_int("TELEMETRY_FACILITY_ID", 1)


def telemetry_feature_sensors() -> dict[str, str]:
    """feature name -> sensor ``external_id`` for the five anomaly features.

    Default ``fac<TELEMETRY_FACILITY_ID>.<feature>``. Override with TELEMETRY_FEATURE_SENSORS, a JSON object
    mapping feature -> external_id (must cover exactly the five features, else the default is used and a warning
    is logged; a partial mapping must never silently score a different sensor).
    """
    default = {f: f"fac{telemetry_facility_id()}.{f}" for f in TELEMETRY_FEATURES}
    raw = os.getenv("TELEMETRY_FEATURE_SENSORS")
    if raw is None or not raw.strip():
        return default
    try:
        import json

        mapping = json.loads(raw)
        if (
            isinstance(mapping, dict)
            and set(mapping) == set(TELEMETRY_FEATURES)
            and all(isinstance(v, str) and v for v in mapping.values())
        ):
            return {f: mapping[f] for f in TELEMETRY_FEATURES}
    except ValueError:
        pass
    _logger.warning(
        "TELEMETRY_FEATURE_SENSORS is not a JSON object covering exactly %s; using the default", TELEMETRY_FEATURES
    )
    return default


def mqtt_queue_max() -> int:
    """MQTT_QUEUE_MAX (default 10000): bound of the in-process MQTT queue; overflow drops the OLDEST message."""
    return _env_positive_int("MQTT_QUEUE_MAX", DEFAULT_MQTT_QUEUE_MAX)


def mqtt_tls_enabled() -> bool:
    """MQTT_TLS (default false): connect to the broker over TLS (system CA bundle)."""
    return os.getenv("MQTT_TLS", "false").strip().lower() in _TRUE_VALUES


def mqtt_credentials() -> tuple[str | None, str | None]:
    """(MQTT_USERNAME, MQTT_PASSWORD); the password may come from MQTT_PASSWORD_FILE. Blank -> None."""
    from api.secrets import read_secret

    user = (os.getenv("MQTT_USERNAME") or "").strip() or None
    password = (read_secret("MQTT_PASSWORD") or "").strip() or None
    return user, password
