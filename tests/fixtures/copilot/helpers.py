"""Shared fixtures for the Copilot tests: known alerts, signals, a passport and a small claims ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.copilot import tools

HERE = Path(__file__).parent
NOW = datetime(2026, 10, 20, 3, 15, tzinfo=timezone.utc)


def load(name: str) -> dict[str, Any]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def alert_loader(name: str = "alert_42.json"):
    data = load(name)
    data["alert"]["created_at"] = datetime.fromisoformat(data["alert"]["created_at"])

    async def _load(alert_id: str):
        return data if alert_id == str(data["alert"]["id"]) else None

    return _load


def signal_loader(name: str = "signal_inlet_fresh.json"):
    data = load(name)
    data["observed_at"] = datetime.fromisoformat(data["observed_at"])

    async def _load(signal: str):
        return data if signal == data["signal"] else None

    return _load


def passport_loader(available: bool = True):
    async def _load():
        return load("passport.json") if available else None

    return _load


def make_ctx(**kw: Any) -> tools.ToolContext:
    defaults: dict[str, Any] = {
        "now": NOW,
        "load_alert": alert_loader(),
        "load_signal": signal_loader(),
        "load_passport": passport_loader(),
        "claims_path": HERE / "claims_small.md",
    }
    return tools.ToolContext(**{**defaults, **kw})
