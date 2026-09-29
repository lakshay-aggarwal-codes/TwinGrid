"""Webhook subscribers for alert events. File-based (JSON), same reasoning
as src/model_registry.py: avoids an untested Alembic migration for a new
table this pass can't verify against a real DB. Move to a DB table when the
app runs more than one worker (the file lock below is per-process only).

Writes are serialised with a lock and made atomic (write temp file, then
os.replace), so concurrent registrations in one process can't lose updates and
a crash mid-write can't leave a truncated file.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

REGISTRY_PATH = Path("data/webhooks.json")
MAX_SUBSCRIBERS = 20

_lock = threading.RLock()


class SubscriberLimitError(Exception):
    """Raised when registering would exceed MAX_SUBSCRIBERS."""


def _load() -> list[str]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return [u for u in data if isinstance(u, str)] if isinstance(data, list) else []


def _save(urls: list[str]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(REGISTRY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(urls, indent=2))
    os.replace(tmp, REGISTRY_PATH)


def register(url: str) -> list[str]:
    with _lock:
        urls = _load()
        if url not in urls:
            if len(urls) >= MAX_SUBSCRIBERS:
                raise SubscriberLimitError(f"At most {MAX_SUBSCRIBERS} webhook subscribers are allowed")
            urls.append(url)
            _save(urls)
        return urls


def unregister(url: str) -> list[str]:
    with _lock:
        urls = [u for u in _load() if u != url]
        _save(urls)
        return urls


def list_subscribers() -> list[str]:
    with _lock:
        return _load()
