"""Task 29: a bounded log of webhook delivery attempts (real alert deliveries and admin test-fires).

File-based, like ``src/webhook_registry.py`` (same reasoning: no new table for a small operational log; the lock is
per-process, so with several workers the log is partial and interleaved, which the admin console says). Newest last on
disk, newest first when read. At most ``MAX_RECORDS`` are kept.

A record holds only: time, kind, the webhook's id and host, whether it was delivered (a 2xx), the status code, an error
KIND, and how long it took. Never the URL path or query, the payload, a response body or an exception message.
Recording never raises: a delivery must not fail because its log could not be written.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from src.admin_console.rules import webhook_id

logger = logging.getLogger(__name__)

LOG_PATH = Path("data/webhook_deliveries.json")
MAX_RECORDS = 200
KINDS = ("alert", "test")
ERROR_KINDS = ("blocked_url", "timeout", "connection", "http_error", "redirect_refused", "request_error")

_lock = threading.RLock()


def make_record(
    kind: str,
    url: str,
    *,
    ok: bool,
    status_code: Optional[int],
    error_kind: Optional[str],
    duration_ms: int,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    return {
        "at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "kind": kind,
        "webhook_id": webhook_id(url),
        "host": urlsplit(url).hostname or "",
        "ok": bool(ok),
        "status_code": status_code,
        "error_kind": error_kind,
        "duration_ms": max(0, int(duration_ms)),
    }


def _load() -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    try:
        data = json.loads(LOG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _save(records: list[dict[str, Any]]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOG_PATH.with_suffix(LOG_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(records))
    os.replace(tmp, LOG_PATH)


def record(entry: dict[str, Any]) -> None:
    """Append one record, keeping the newest ``MAX_RECORDS``. Never raises."""
    try:
        with _lock:
            records = _load()
            records.append(entry)
            _save(records[-MAX_RECORDS:])
    except Exception:  # noqa: BLE001 - logging a delivery must never fail the delivery
        logger.warning("Could not record a webhook delivery", exc_info=True)


def recent(limit: int = 50, webhook: Optional[str] = None) -> list[dict[str, Any]]:
    """Newest first; optionally only one webhook's records."""
    with _lock:
        records = _load()
    if webhook is not None:
        records = [r for r in records if r.get("webhook_id") == webhook]
    return list(reversed(records))[: max(0, limit)]
