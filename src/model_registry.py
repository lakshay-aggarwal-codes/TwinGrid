"""Lightweight local model registry: append-only JSON log of every training
run -- what was trained, when, on what data, with what metrics, to which
artifact path. Not MLflow (needs a tracking server, a new heavy dependency,
and isn't verifiable in the assistant's sandbox); this covers the actual
Phase-2 need -- "which model version is deployed, with which metrics,
trained on what" -- with zero new dependencies. Swap for MLflow later if the
team wants a UI/server; the call sites (log_model calls in
notebooks/train_all.py) would barely change.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path("models/registry.json")


def log_model(
    name: str,
    *,
    metrics: dict[str, Any],
    data_source: str,
    artifact_path: str,
    params: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Append one entry. Never overwrites prior entries -- full lineage
    history, newest last. This registry doesn't move/symlink files; the
    "deployed" model is still just whatever artifact_path points at on
    disk. version defaults to a UTC timestamp.
    """
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    if REGISTRY_PATH.exists():
        try:
            entries = json.loads(REGISTRY_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            entries = []

    entry = {
        "name": name,
        "version": version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "data_source": data_source,
        "artifact_path": artifact_path,
        "params": params or {},
        "python": platform.python_version(),
    }
    entries.append(entry)
    REGISTRY_PATH.write_text(json.dumps(entries, indent=2))
    return entry


def latest(name: str) -> dict[str, Any] | None:
    """Most recent registry entry for a model name, or None if never logged."""
    if not REGISTRY_PATH.exists():
        return None
    try:
        entries = json.loads(REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    matches = [e for e in entries if e.get("name") == name]
    return matches[-1] if matches else None
