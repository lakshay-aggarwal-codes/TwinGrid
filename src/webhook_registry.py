"""Webhook subscribers for alert events. File-based (JSON), same reasoning
as src/model_registry.py: avoids an untested Alembic migration for a new
table this pass can't verify against a real DB. Move to a DB table later
if/when subscriber count or query needs grow past what a JSON file
comfortably handles.
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path("data/webhooks.json")


def _load() -> list[str]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(urls: list[str]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(urls, indent=2))


def register(url: str) -> list[str]:
    urls = _load()
    if url not in urls:
        urls.append(url)
        _save(urls)
    return urls


def unregister(url: str) -> list[str]:
    urls = [u for u in _load() if u != url]
    _save(urls)
    return urls


def list_subscribers() -> list[str]:
    return _load()

