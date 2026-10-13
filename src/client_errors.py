"""Browser error reports (Task 7): settings, validation and sanitising. Pure; the HTTP side is api/plugins/client_errors.py.

The input is exactly what ``twin-stream-insight-main/src/lib/errorReporter.ts`` sends (``ErrorReport``): a JSON object
``{level, source, message, stack?, page, timestamp}`` posted as ``text/plain`` by ``navigator.sendBeacon`` (so no
``Authorization`` header and no custom header can be attached). Anything else in the object is dropped.

Environment (read on every call, defaults in brackets):
``CLIENT_ERRORS_MAX_BYTES`` [8192], ``CLIENT_ERRORS_RATE_LIMIT`` [20/minute, per client IP],
``CLIENT_ERRORS_REPORT_KEY`` [unset; at least 16 characters, sent as ``?key=`` in VITE_ERROR_REPORT_URL].
"""

from __future__ import annotations

import hmac
import json
import os
import re
from typing import Any

from src.log_redaction import redact

DEFAULT_MAX_BYTES = 8192
MIN_MAX_BYTES, MAX_MAX_BYTES = 256, 65536
DEFAULT_RATE_LIMIT = "20/minute"
MIN_KEY_CHARS = 16
LEVELS = ("warning", "error")
FIELD_LIMITS = {"source": 200, "message": 500, "stack": 2000, "page": 200, "timestamp": 40}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # keeps tab and newline (stack traces); JSON logging escapes them


class InvalidReport(ValueError):
    """The body is not a well-formed report. The message is client-safe (never echoes the input)."""


def max_bytes() -> int:
    try:
        value = int(os.getenv("CLIENT_ERRORS_MAX_BYTES", ""))
    except ValueError:
        return DEFAULT_MAX_BYTES
    return min(MAX_MAX_BYTES, max(MIN_MAX_BYTES, value))


def rate_limit() -> str:
    return os.getenv("CLIENT_ERRORS_RATE_LIMIT", "").strip() or DEFAULT_RATE_LIMIT


def configured_key() -> str | None:
    """The report key, or None when unset or too short to be a key (a short key counts as not configured)."""
    key = os.getenv("CLIENT_ERRORS_REPORT_KEY", "").strip()
    return key if len(key) >= MIN_KEY_CHARS else None


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").strip().lower() not in ("development", "test")


def key_matches(provided: str | None) -> bool:
    expected = configured_key()
    return bool(expected and provided) and hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))  # type: ignore[union-attr]


def parse_report(raw: bytes) -> dict[str, str]:
    """Validate ``raw`` and return the sanitised fields (secrets redacted, control characters removed, lengths capped)."""
    try:
        data: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise InvalidReport("body is not valid JSON") from None
    if not isinstance(data, dict):
        raise InvalidReport("body must be a JSON object")
    if data.get("level") not in LEVELS:
        raise InvalidReport("level must be 'warning' or 'error'")
    out: dict[str, str] = {"level": data["level"]}
    for name, limit in FIELD_LIMITS.items():
        value = data.get(name)
        if value is None and name == "stack":
            continue
        if not isinstance(value, str):
            raise InvalidReport(f"{name} must be a string")
        if name != "stack" and not value:
            raise InvalidReport(f"{name} must not be empty")
        out[name] = _CONTROL.sub("", redact(value))[:limit]
    return out
