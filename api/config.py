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
    # T17: GET /api/telemetry/sensors/{external_id}/samples|gaps (own class: range reads are heavier than /state).
    "telemetry_read": ("RATE_LIMIT_TELEMETRY_READ", "60/minute"),
    # T14: applied (at include_router level, see api/main.py) to every route that has no scope of its own.
    "general": ("RATE_LIMIT_GENERAL", "120/minute"),
}

# Paths never rate limited (infrastructure probes): /livez, /readyz and the deprecated /healthz alias.
HTTP_LIMIT_EXEMPT_PATHS: frozenset[str] = frozenset({"/livez", "/readyz", "/healthz"})

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
# Runtime reliability (T18): fan-out, supervision, readiness. Read on every call.
# -----------------------------------------------------------------------------

DEFAULT_WS_SEND_TIMEOUT_S = 2.0
DEFAULT_WS_CLIENT_QUEUE_MAX = 1
MAX_WS_CLIENT_QUEUE_MAX = 10
# Backstop only: a client that has had this many frames dropped in a row without ONE completed send is closed
# with 1013. tests/test_ws_fanout.py (memory test) drops 2000 frames on a stalled client and expects it to still be
# registered, so the default sits well above that; a truly stalled client is evicted by the send timeout long before.
DEFAULT_WS_MAX_CONSECUTIVE_DROPS = 5000
DEFAULT_TICK_TIMEOUT_S = 10.0
DEFAULT_SUPERVISOR_MAX_RESTARTS = 10
DEFAULT_SUPERVISOR_RESTART_WINDOW_S = 600.0
DEFAULT_SHUTDOWN_DEADLINE_S = 10.0

# Contract names (isolated / sequential) and the names tests/test_ws_fanout.py already uses (concurrent / serial).
_BROADCAST_MODES = {
    "isolated": "concurrent",
    "concurrent": "concurrent",
    "sequential": "serial",
    "serial": "serial",
}


def _first_env(*names: str) -> tuple[str, str] | None:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and raw.strip():
            return name, raw.strip()
    return None


def _positive_float_from(names: tuple[str, ...], default: float) -> float:
    found = _first_env(*names)
    if found is None:
        return default
    name, raw = found
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not 0 < value < float("inf"):
        _logger.warning("%s=%r is not a positive number; using default %s", name, raw, default)
        return default
    return value


def _positive_int_from(names: tuple[str, ...], default: int, *, maximum: int | None = None) -> int:
    found = _first_env(*names)
    if found is None:
        return default
    name, raw = found
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        _logger.warning("%s=%r is not a positive integer; using default %d", name, raw, default)
        return default
    if maximum is not None and value > maximum:
        _logger.warning("%s=%d is above the maximum %d; using %d", name, value, maximum, maximum)
        return maximum
    return value


def broadcast_mode() -> str:
    """BROADCAST_MODE: ``isolated`` (default; also ``concurrent``) or ``sequential`` (also ``serial``, the rollback).
    Returns the internal name, ``concurrent`` or ``serial``; anything unknown means ``concurrent``."""
    raw = os.getenv("BROADCAST_MODE", "").strip().lower()
    return _BROADCAST_MODES.get(raw, "concurrent")


def ws_send_timeout_s() -> float:
    """WS_SEND_TIMEOUT_S (alias BROADCAST_SEND_TIMEOUT_SECONDS), default 2.0: one frame must be sent within it."""
    return _positive_float_from(("WS_SEND_TIMEOUT_S", "BROADCAST_SEND_TIMEOUT_SECONDS"), DEFAULT_WS_SEND_TIMEOUT_S)


def ws_client_queue_max() -> int:
    """WS_CLIENT_QUEUE_MAX (alias BROADCAST_QUEUE_DEPTH), default 1, at most 10: frames waiting per client."""
    return _positive_int_from(
        ("WS_CLIENT_QUEUE_MAX", "BROADCAST_QUEUE_DEPTH"), DEFAULT_WS_CLIENT_QUEUE_MAX, maximum=MAX_WS_CLIENT_QUEUE_MAX
    )


def ws_max_consecutive_drops() -> int:
    """WS_MAX_CONSECUTIVE_DROPS (default 5000): consecutive dropped frames before a client is closed with 1013."""
    return _positive_int_from(("WS_MAX_CONSECUTIVE_DROPS",), DEFAULT_WS_MAX_CONSECUTIVE_DROPS)


def tick_timeout_s() -> float:
    """TICK_TIMEOUT_S (default 10): wall-clock budget of one supervised tick (a hung tick is cancelled)."""
    return _positive_float_from(("TICK_TIMEOUT_S",), DEFAULT_TICK_TIMEOUT_S)


def supervisor_max_restarts() -> int:
    """SUPERVISOR_MAX_RESTARTS (default 10) per SUPERVISOR_RESTART_WINDOW_S (default 600): more means give up."""
    return _positive_int_from(("SUPERVISOR_MAX_RESTARTS",), DEFAULT_SUPERVISOR_MAX_RESTARTS)


def supervisor_restart_window_s() -> float:
    return _positive_float_from(("SUPERVISOR_RESTART_WINDOW_S",), DEFAULT_SUPERVISOR_RESTART_WINDOW_S)


def shutdown_deadline_s() -> float:
    """SHUTDOWN_DEADLINE_S (default 10): background tasks get this long to finish after cancel."""
    return _positive_float_from(("SHUTDOWN_DEADLINE_S",), DEFAULT_SHUTDOWN_DEADLINE_S)


def readyz_check_schema() -> bool:
    """READYZ_CHECK_SCHEMA (default true). ``false`` skips the Alembic-head check (create_all-built dev databases)."""
    return os.getenv("READYZ_CHECK_SCHEMA", "true").strip().lower() not in {"0", "false", "no", "off"}


# -----------------------------------------------------------------------------
# Time contract (T20). Read on every call.
# -----------------------------------------------------------------------------

DEFAULT_SIM_STEP_SECONDS = 300  # A-1: one simulated tick is 5 minutes
DEFAULT_SITE_TIMEZONE = "Asia/Kolkata"


def sim_step_seconds() -> float:
    """SIM_STEP_SECONDS (default 300): simulated seconds per live tick.

    Unlike ``src.physics.v2.sim_step_seconds`` (which raises on a bad value) this is the *serving* read:
    a malformed or non-positive value falls back to the strict default and says so in the log.
    """
    return _env_positive_float("SIM_STEP_SECONDS", float(DEFAULT_SIM_STEP_SECONDS))


# -----------------------------------------------------------------------------
# Telemetry store and MQTT consumer (T16/T17). Read on every call.
# -----------------------------------------------------------------------------

DEFAULT_TELEMETRY_MAX_SPAN_H = 168
DEFAULT_TELEMETRY_FACILITY_ID = 1
DEFAULT_MQTT_QUEUE_MAX = 10_000

# The five anomaly-model inputs, in the model's own order (models/anomaly/config.json: feature_columns).
TELEMETRY_FEATURES: tuple[str, ...] = (
    "water_flow_lpm",
    "water_pressure_bar",
    "server_outlet_temp_C",
    "it_power_kw",
    "humidity_pct",
)

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def telemetry_store_enabled() -> bool:
    """TELEMETRY_STORE_ENABLED (default true). ``false`` is the rollback: legacy ``sensor_readings`` write path."""
    return os.getenv("TELEMETRY_STORE_ENABLED", "true").strip().lower() not in _FALSE_VALUES


def telemetry_window_source() -> str:
    """TELEMETRY_WINDOW_SOURCE: ``store`` (default) or ``memory`` (in-process ring buffer, the rollback).

    Any other value does NOT select ``memory``: it falls back to ``store`` so a typo cannot silently
    switch the anomaly pipeline onto the unaudited in-memory window.
    """
    raw = os.getenv("TELEMETRY_WINDOW_SOURCE", "store").strip().lower()
    if raw == "memory":
        return "memory"
    if raw not in ("", "store"):
        _logger.warning("TELEMETRY_WINDOW_SOURCE=%r is not 'store' or 'memory'; using 'store'", raw)
    return "store"


def telemetry_max_span_h() -> int:
    """TELEMETRY_MAX_SPAN_H (default 168): longest ``to - from`` the telemetry read API accepts."""
    return _env_positive_int("TELEMETRY_MAX_SPAN_H", DEFAULT_TELEMETRY_MAX_SPAN_H)


def telemetry_facility_id() -> int:
    """TELEMETRY_FACILITY_ID (default 1): facility whose ``fac<ID>.<measurand>`` sensors feed the anomaly window."""
    return _env_positive_int("TELEMETRY_FACILITY_ID", DEFAULT_TELEMETRY_FACILITY_ID)


def telemetry_feature_sensors() -> dict[str, str]:
    """Feature -> sensor ``external_id`` for the five anomaly features, in model order.

    Default mapping is ``fac<TELEMETRY_FACILITY_ID>.<feature>``. ``TELEMETRY_FEATURE_SENSORS`` may hold a JSON
    object overriding it; it must cover exactly the five features, otherwise it is ignored (with a warning).
    """
    import json

    default = {f: f"fac{telemetry_facility_id()}.{f}" for f in TELEMETRY_FEATURES}
    raw = os.getenv("TELEMETRY_FEATURE_SENSORS")
    if raw is None or not raw.strip():
        return default
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if (
        not isinstance(parsed, dict)
        or set(parsed) != set(TELEMETRY_FEATURES)
        or not all(isinstance(v, str) and v.strip() for v in parsed.values())
    ):
        _logger.warning(
            "TELEMETRY_FEATURE_SENSORS must be a JSON object covering exactly %s; using default", TELEMETRY_FEATURES
        )
        return default
    return {f: parsed[f].strip() for f in TELEMETRY_FEATURES}


def mqtt_credentials() -> tuple[str | None, str | None]:
    """(username, password) for the MQTT broker, each from ``MQTT_USERNAME`` / ``MQTT_PASSWORD`` or its ``_FILE``.

    Blank -> ``None``. Never logged.
    """
    from api.secrets import read_secret

    def _clean(value: str | None) -> str | None:
        return value if value and value.strip() else None

    return _clean(read_secret("MQTT_USERNAME")), _clean(read_secret("MQTT_PASSWORD"))


def mqtt_tls_enabled() -> bool:
    """MQTT_TLS (default false): wrap the broker connection in TLS (system CA bundle, hostname checked)."""
    return os.getenv("MQTT_TLS", "").strip().lower() in _TRUE_VALUES


def mqtt_queue_max() -> int:
    """MQTT_QUEUE_MAX (default 10000): bound of the in-process queue. Malformed -> default, never unbounded."""
    return _env_positive_int("MQTT_QUEUE_MAX", DEFAULT_MQTT_QUEUE_MAX)
