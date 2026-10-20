"""Tokens, references and keyed hashes for access requests.

* A token is 32 random bytes, URL-safe (43 characters). Only its HMAC-SHA256 (hex, 64 chars) is stored.
* The HMAC key is ``ACCESS_TOKEN_PEPPER`` (read through ``api.secrets.read_secret``, so ``ACCESS_TOKEN_PEPPER_FILE``
  works). It is required when ``ENVIRONMENT=production``; in development a fixed, public default is used and a warning
  is logged once.
* A DECOY (ref, token) pair answers a submission for an address that must not be revealed (already a user, already
  approved). It is derived from the pepper alone, stores nothing and verifies statelessly: the ref encodes the UTC day
  it was issued (masked), the token is ``nonce || HMAC(nonce, ref)``. The ref is the same for the same (email, UTC day),
  like a real duplicate-pending submission, and the token changes on every call, like a rotated real token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TOKEN_BYTES = 32
TOKEN_LEN = 43  # urlsafe base64 of 32 bytes, unpadded
REF_LEN = 12
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_DEV_PEPPER = "twingrid-dev-access-pepper-NOT-A-SECRET"
_warned = False


class PepperMissing(RuntimeError):
    """ACCESS_TOKEN_PEPPER is not set and ENVIRONMENT=production."""


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").strip().lower() == "production"


def pepper() -> bytes:
    global _warned
    from api.secrets import read_secret  # lazy: keeps this module importable on its own

    value = read_secret("ACCESS_TOKEN_PEPPER")
    if value and value.strip():
        return value.strip().encode("utf-8")
    if _is_production():
        raise PepperMissing("ACCESS_TOKEN_PEPPER must be set when ENVIRONMENT=production")
    if not _warned:
        _warned = True
        logger.warning("ACCESS_TOKEN_PEPPER is not set; using the public development default (not for production)")
    return _DEV_PEPPER.encode("utf-8")


def _mac(label: str, *parts: str | bytes) -> bytes:
    msg = label.encode("ascii") + b"".join(b"\x00" + (p if isinstance(p, bytes) else p.encode("utf-8")) for p in parts)
    return hmac.new(pepper(), msg, hashlib.sha256).digest()


# ----------------------------------------------------------------------------- tokens and hashes


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """HMAC-SHA256 hex of a token (64 chars)."""
    return _mac("token", token).hex()


def tokens_match(token: str, stored_hash: str | None) -> bool:
    """Constant-time check of a presented token against a stored hash. Never raises on odd input."""
    if not isinstance(token, str) or not stored_hash or len(token) != TOKEN_LEN:
        # still do the comparison work so the time does not depend on which check failed
        hmac.compare_digest(hash_token(str(token)[:256]), stored_hash or "0" * 64)
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)


def hash_ip(ip: str | None) -> str:
    return _mac("ip", ip or "unknown").hex()


def hash_email_for_limit(email_normalized: str) -> str:
    """Key for the per-email rate limit: the address itself is not kept in the in-memory windows."""
    return _mac("email-limit", email_normalized).hex()[:32]


# ----------------------------------------------------------------------------- refs


def _int_to_ref(value: int) -> str:
    chars = []
    for _ in range(REF_LEN):
        chars.append(_B32[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def _ref_to_int(ref: str) -> int | None:
    if not isinstance(ref, str) or len(ref) != REF_LEN or any(c not in _B32 for c in ref):
        return None
    value = 0
    for c in ref:
        value = (value << 5) | _B32.index(c)
    return value


def new_ref() -> str:
    """12 base32 characters (60 random bits)."""
    return _int_to_ref(secrets.randbits(60))


# ----------------------------------------------------------------------------- decoys

_DAY = 86400


def _day_index(now: datetime) -> int:
    return int(now.astimezone(timezone.utc).timestamp()) // _DAY


def decoy_ref(email_normalized: str, now: datetime) -> str:
    """60 bits = 16 (masked UTC day index) + 44 (HMAC of email and day)."""
    day = _day_index(now)
    low = int.from_bytes(_mac("decoy-ref", email_normalized, str(day))[:6], "big") & ((1 << 44) - 1)
    mask = int.from_bytes(_mac("decoy-day", str(low))[:2], "big")
    return _int_to_ref((((day & 0xFFFF) ^ mask) << 44) | low)


def decoy_ref_and_token(email_normalized: str, now: datetime) -> tuple[str, str]:
    ref = decoy_ref(email_normalized, now)
    nonce = secrets.token_bytes(16)
    tag = _mac("decoy-token", ref, nonce)[:16]
    return ref, base64.urlsafe_b64encode(nonce + tag).rstrip(b"=").decode("ascii")


def verify_decoy(ref: str, token: str, now: datetime, max_age_days: float) -> datetime | None:
    """The UTC start of the day a valid decoy (ref, token) was issued, or None. Valid for ``max_age_days`` after that."""
    value = _ref_to_int(ref)
    if value is None or not isinstance(token, str) or len(token) != TOKEN_LEN:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=")
    except (ValueError, TypeError):
        return None
    if len(raw) != 32:
        return None
    nonce, tag = raw[:16], raw[16:]
    if not hmac.compare_digest(_mac("decoy-token", ref, nonce)[:16], tag):
        return None
    low = value & ((1 << 44) - 1)
    mask = int.from_bytes(_mac("decoy-day", str(low))[:2], "big")
    day_low16 = (value >> 44) ^ mask
    today = _day_index(now)
    # recover the full day index from its low 16 bits (65536 days = ~179 years; pick the one nearest to today)
    day = today - ((today - day_low16) & 0xFFFF)
    if day > today or (today - day) > max_age_days:
        return None
    return datetime.fromtimestamp(day * _DAY, tz=timezone.utc)
