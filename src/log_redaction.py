"""Secret redaction for log text (Task 7). Pure: no I/O, no clock, no imports beyond ``re``.

``redact(text)`` rewrites, wherever they appear in free text, JSON or key=value pairs:

* URL / query-string secrets: ``?token=``, ``&ticket=``, ``access_token``, ``refresh_token``, ``key`` and ``password``;
* an ``Authorization`` header value and any ``Bearer`` / ``Basic`` credential;
* values of fields whose NAME says they are secret (``password``, ``secret``, ``token``, ``ticket``, ``api_key``,
  ``admin_key``, e.g. ``"password": "x"``, ``JWT_SECRET_KEY=x``, ``refresh_token: x``);
* JWT-shaped strings (``eyJ...``), whatever precedes them.

It errs on the side of redacting too much: a log line is never worth a credential. Idempotent.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_QUERY = re.compile(r"""(?i)([?&;](?:token|ticket|access_token|refresh_token|key|password|api_key)=)[^&\s"'`)<>]*""")
_AUTH_HEADER = re.compile(r"""(?i)(\bauthorization["']?\s*[:=]\s*["']?)[^"',;}\r\n]+""")
_SCHEME = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_NAMED = re.compile(
    r"""(?ix)
    (["']?[\w-]*(?:password|passwd|secret|token|ticket|api[_-]?key|admin[_-]?key)[\w-]*["']?\s*[:=]\s*)
    (\[REDACTED\]|"(?:[^"\\]|\\.)*"|'[^']*'|[^\s,;&}\]"']+)
    """
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*")


def _named(match: re.Match[str]) -> str:
    value = match.group(2)
    if value == REDACTED:
        return match.group(0)
    quote = value[0] if value[0] in "\"'" else ""
    return f"{match.group(1)}{quote}{REDACTED}{quote}"


def redact(text: str) -> str:
    """``text`` with every secret recognised above replaced by ``[REDACTED]``."""
    if not text:
        return text
    text = _QUERY.sub(rf"\1{REDACTED}", text)
    text = _AUTH_HEADER.sub(rf"\1{REDACTED}", text)
    text = _SCHEME.sub(rf"\1 {REDACTED}", text)
    text = _NAMED.sub(_named, text)
    return _JWT.sub(REDACTED, text)


def redact_value(value: Any) -> Any:
    """``redact`` applied to every string inside str / list / tuple / dict values (other types are untouched)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value]
    return value
