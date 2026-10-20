"""Pure rules for access requests: normalisation, validation, TTLs. No I/O, no database."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import timedelta

EMAIL_MAX = 64  # users.username is String(64)
NAME_MAX = 80
PURPOSE_MAX = 500
NOTE_MAX = 500
PASSWORD_MIN = 12
PASSWORD_MAX = 128

_EMAIL_RE = re.compile(r"^[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+\.[^@\s\x00-\x1f\x7f]+$")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CODE_RE = re.compile(r"^[a-z0-9_]{1,24}$")


class InvalidRequest(ValueError):
    """The submission is not acceptable. The message is for logs/tests only; clients get a generic body."""


@dataclass(frozen=True)
class Submission:
    name: str
    email: str  # normalised
    purpose: str | None


def normalise_email(raw: object) -> str:
    """strip + casefold; rejects non-strings, anything that is not ``local@domain.tld`` and anything over 64 chars."""
    if not isinstance(raw, str):
        raise InvalidRequest("email must be a string")
    email = raw.strip().casefold()
    if not email or len(email) > EMAIL_MAX or not _EMAIL_RE.match(email):
        raise InvalidRequest("email is not acceptable")
    return email


def clean_text(raw: object, *, field: str, max_len: int, required: bool) -> str | None:
    if raw is None and not required:
        return None
    if not isinstance(raw, str):
        raise InvalidRequest(f"{field} must be a string")
    text = raw.strip()
    if _CTRL_RE.search(text):
        raise InvalidRequest(f"{field} has control characters")
    if not text:
        if required:
            raise InvalidRequest(f"{field} is required")
        return None
    if len(text) > max_len:
        raise InvalidRequest(f"{field} is too long")
    return text


def parse_submission(body: object) -> Submission:
    if not isinstance(body, dict):
        raise InvalidRequest("body must be an object")
    return Submission(
        name=clean_text(body.get("name"), field="name", max_len=NAME_MAX, required=True) or "",
        email=normalise_email(body.get("email")),
        purpose=clean_text(body.get("purpose"), field="purpose", max_len=PURPOSE_MAX, required=False),
    )


def clean_note(raw: object) -> str | None:
    """Optional admin decision note. A bad note is an InvalidRequest (422), never silently dropped."""
    return clean_text(raw, field="note", max_len=NOTE_MAX, required=False)


def password_problem(password: object, email_normalized: str | None = None) -> str | None:
    """None if acceptable, else a short machine code. 12-128 chars, not equal to the email."""
    if not isinstance(password, str) or not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        return "length"
    if email_normalized is not None and password.strip().casefold() == email_normalized:
        return "equals_email"
    return None


def safe_code(code: object, default: str = "error") -> str:
    """A result code for ``notify_last_code`` (<= 24 chars, ``[a-z0-9_]``); anything else becomes ``default``.
    Exception text can never get through this."""
    return code if isinstance(code, str) and _CODE_RE.match(code) else default


def _env_positive_number(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def request_ttl() -> timedelta:
    return timedelta(days=_env_positive_number("ACCESS_REQUEST_TTL_DAYS", 7))


def activation_ttl() -> timedelta:
    return timedelta(hours=_env_positive_number("ACCESS_ACTIVATION_TTL_HOURS", 24))


def requests_enabled() -> bool:
    return os.getenv("ACCESS_REQUESTS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
