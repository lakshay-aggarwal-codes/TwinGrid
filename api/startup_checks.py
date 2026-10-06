"""Startup validation (T13): refuse to start with unsafe production settings.

Rules live in one table (``RULES``). Each rule has an id, the variable NAMES it concerns and a predicate
that is true when the rule is violated. A violation is reported by variable name only -- never by value --
so the message is safe to print to logs, CI output and ``docker logs``.

Only ``ENVIRONMENT=production`` gets the strict rules. ``development`` and ``test`` (the repo's own CI and
dev values) are deliberately left alone: the rules are not weakened, they simply apply to production.

    python -m api.startup_checks      # exit 0 if valid, 1 with variable names on stderr (used by the Dockerfile CMD)

This module reads the environment only; it must not import ``api.config`` or ``api.auth`` (both import it).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from api.secrets import read_secret

VALID_ENVIRONMENTS = ("development", "test", "production")
DEFAULT_ENVIRONMENT = "development"

MIN_SECRET_LENGTH = 32

# Values that ship in this repository and must never be a production secret.
KNOWN_UNSAFE_SECRETS = frozenset(
    {
        "your-secret-key-here-change-in-production",  # .env.example JWT_SECRET_KEY
        "ci-test-secret-not-for-production",  # .github/workflows/ci.yml
        "test-secret-for-suite-only",  # tests/
        "change-me-to-a-long-random-string",  # .env.example OPERATOR_REGISTRATION_KEY
        "change-me-to-a-long-random-metrics-token",  # .env.example METRICS_TOKEN
    }
)
_TRUTHY = {"1", "true", "yes", "on"}

# Every environment variable this module (and api/config.py's startup rules) reads. tests/test_startup_checks.py
# asserts each one appears in .env.example.
ENV_VARS_READ = (
    "ENVIRONMENT",
    "JWT_SECRET_KEY",
    "METRICS_TOKEN",
    "CORS_ALLOWED_ORIGINS",
    "DATABASE_URL",
    "OPERATOR_REGISTRATION_KEY",
    "MOCK_SENSORS",
    "MQTT_BROKER",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
)


class StartupConfigError(RuntimeError):
    """Unsafe or invalid startup configuration. ``variables`` holds variable NAMES only, never values.

    Subclasses RuntimeError so existing ``except RuntimeError`` / ``pytest.raises(RuntimeError)`` callers still work.
    """

    def __init__(self, variables: list[str], detail: str = "") -> None:
        self.variables = sorted(set(variables))
        text = "Refusing to start: unsafe or invalid configuration. Variables: " + ", ".join(self.variables) + "."
        if detail:
            text += " " + detail
        super().__init__(text)


# ----------------------------------------------------------------------------- environment helpers


def raw_environment() -> str:
    """ENVIRONMENT normalised the same way every other reader in the repo does (strip + lower; unset -> development)."""
    return os.getenv("ENVIRONMENT", DEFAULT_ENVIRONMENT).strip().lower()


def is_valid_environment(name: str | None = None) -> bool:
    return (raw_environment() if name is None else name) in VALID_ENVIRONMENTS


def requires_strict_checks() -> bool:
    """True for production AND for an unrecognised ENVIRONMENT: unknown fails closed, never open."""
    name = raw_environment()
    return name == "production" or name not in VALID_ENVIRONMENTS


def _secret(name: str) -> str:
    """The secret (``NAME`` or ``NAME_FILE``), stripped; "" when unset. An unreadable ``_FILE`` raises
    StartupConfigError naming the variable (the path is not echoed)."""
    try:
        return (read_secret(name) or "").strip()
    except RuntimeError as exc:
        raise StartupConfigError([f"{name}_FILE"], "The file could not be read.") from exc


# ----------------------------------------------------------------------------- the rule table


@dataclass(frozen=True)
class Rule:
    id: str
    variables: tuple[str, ...]
    production_only: bool
    violated: Callable[[], bool]
    why: str


def _weak(value: str) -> bool:
    return len(value) < MIN_SECRET_LENGTH


def _jwt_missing() -> bool:
    return not _secret("JWT_SECRET_KEY")


def _jwt_unsafe_value() -> bool:
    value = _secret("JWT_SECRET_KEY")
    return bool(value) and value in KNOWN_UNSAFE_SECRETS


def _jwt_weak() -> bool:
    value = _secret("JWT_SECRET_KEY")
    return bool(value) and _weak(value)


def _metrics_missing() -> bool:
    return not _secret("METRICS_TOKEN")


def _metrics_unsafe_value() -> bool:
    value = _secret("METRICS_TOKEN")
    return bool(value) and value in KNOWN_UNSAFE_SECRETS


def _metrics_weak() -> bool:
    value = _secret("METRICS_TOKEN")
    return bool(value) and _weak(value)


def _cors_unset_or_wildcard() -> bool:
    origins = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return not origins or "*" in origins


def _database_unsafe() -> bool:
    url = _secret("DATABASE_URL")
    if not url:
        return True  # database.py would fall back to the built-in localhost postgres:postgres URL
    return "://postgres:postgres@" in url.lower()


def _operator_key_placeholder() -> bool:
    return _secret("OPERATOR_REGISTRATION_KEY") in KNOWN_UNSAFE_SECRETS and bool(_secret("OPERATOR_REGISTRATION_KEY"))


def _mock_sensors_on() -> bool:
    return os.getenv("MOCK_SENSORS", "").strip().lower() in _TRUTHY


def _mqtt_in_use() -> bool:
    """The MQTT consumer is configured for real use: a broker is named and mock mode is off."""
    return bool(os.getenv("MQTT_BROKER", "").strip()) and not _mock_sensors_on()


def _mqtt_credentials_missing() -> bool:
    return _mqtt_in_use() and not (_secret("MQTT_USERNAME") and _secret("MQTT_PASSWORD"))


RULES: tuple[Rule, ...] = (
    Rule(
        "R01-env-name",
        ("ENVIRONMENT",),
        False,
        lambda: not is_valid_environment(),
        "ENVIRONMENT must be one of development|test|production.",
    ),
    Rule("R02-jwt-missing", ("JWT_SECRET_KEY",), False, _jwt_missing, "JWT_SECRET_KEY (or _FILE) is required."),
    Rule(
        "R03-jwt-known-value",
        ("JWT_SECRET_KEY",),
        True,
        _jwt_unsafe_value,
        "JWT_SECRET_KEY is a placeholder/test value that ships with this repository.",
    ),
    Rule(
        "R04-jwt-weak",
        ("JWT_SECRET_KEY",),
        True,
        _jwt_weak,
        f"JWT_SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters.",
    ),
    Rule(
        "R05-metrics-token-missing",
        ("METRICS_TOKEN",),
        True,
        _metrics_missing,
        "METRICS_TOKEN (or _FILE) is required: /metrics is bearer-protected in production.",
    ),
    Rule(
        "R06-metrics-token-known-value",
        ("METRICS_TOKEN",),
        True,
        _metrics_unsafe_value,
        "METRICS_TOKEN is a placeholder value that ships with this repository.",
    ),
    Rule(
        "R07-metrics-token-weak",
        ("METRICS_TOKEN",),
        True,
        _metrics_weak,
        f"METRICS_TOKEN must be at least {MIN_SECRET_LENGTH} characters.",
    ),
    Rule(
        "R08-cors",
        ("CORS_ALLOWED_ORIGINS",),
        True,
        _cors_unset_or_wildcard,
        "CORS_ALLOWED_ORIGINS must be set explicitly and must not contain '*'.",
    ),
    Rule(
        "R09-database-url",
        ("DATABASE_URL",),
        True,
        _database_unsafe,
        "DATABASE_URL must be set and must not use the default postgres:postgres credentials.",
    ),
    Rule(
        "R10-operator-key",
        ("OPERATOR_REGISTRATION_KEY",),
        True,
        _operator_key_placeholder,
        "OPERATOR_REGISTRATION_KEY is a placeholder value (unset disables operator registration).",
    ),
    Rule(
        "R11-mock-sensors",
        ("MOCK_SENSORS",),
        True,
        _mock_sensors_on,
        "MOCK_SENSORS generates synthetic data and is dev/demo only.",
    ),
    Rule(
        "R12-mqtt-credentials",
        ("MQTT_USERNAME", "MQTT_PASSWORD"),
        True,
        _mqtt_credentials_missing,
        "MQTT_BROKER is set, so MQTT_USERNAME and MQTT_PASSWORD (or _FILE) are required.",
    ),
)


def find_violations(environment: str | None = None) -> list[Rule]:
    """Rules violated under ``environment`` (default: the current ENVIRONMENT). Never includes values."""
    name = raw_environment() if environment is None else environment
    strict = name == "production" or name not in VALID_ENVIRONMENTS
    return [rule for rule in RULES if (strict or not rule.production_only) and rule.violated()]


def validate_startup_config() -> None:
    """Raise StartupConfigError (names only) if the current environment is unsafe; otherwise return."""
    violated = find_violations()
    if violated:
        names: list[str] = []
        for rule in violated:
            names.extend(rule.variables)
        raise StartupConfigError(names, "Rules: " + ", ".join(rule.id for rule in violated) + ".")


def validate_mqtt_config(*, consumer_running: bool = False) -> None:
    """Only the MQTT rule (R12). Called by the standalone ingestion process (``python -m src.sensor_ingestion``),
    which should not need the API's JWT/CORS settings just to consume a broker.

    ``consumer_running=True`` means this process IS the MQTT consumer (not mock mode), so credentials are required
    in production even when MQTT_BROKER is left at its default (``localhost``)."""
    rule = next(r for r in RULES if r.id == "R12-mqtt-credentials")
    if not requires_strict_checks():
        return
    missing = not (_secret("MQTT_USERNAME") and _secret("MQTT_PASSWORD"))
    if rule.violated() or (consumer_running and missing):
        raise StartupConfigError(list(rule.variables), "Rules: " + rule.id + ".")


def check_jwt_secret(value: str | None) -> str:
    """Used by api/auth.py at import: return the secret or raise. Missing is fatal everywhere (as before);
    a repo placeholder or a short value is fatal in production only."""
    secret = (value or "").strip()
    if not secret:
        raise StartupConfigError(
            ["JWT_SECRET_KEY"],
            "JWT_SECRET_KEY (or JWT_SECRET_KEY_FILE) is not set. There is no default; generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"',
        )
    if requires_strict_checks() and (secret in KNOWN_UNSAFE_SECRETS or _weak(secret)):
        raise StartupConfigError(["JWT_SECRET_KEY"], "The value is a placeholder, a test value, or too short.")
    assert value is not None  # non-empty after the check above
    return value  # exactly as configured: callers rely on it


def main() -> int:
    try:
        validate_startup_config()
    except StartupConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
