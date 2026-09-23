"""Shared response-serialization helpers, used by every route that returns
DigitalTwin state (which contains a raw datetime timestamp)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def serialize_timestamps(record: dict[str, Any]) -> dict[str, Any]:
    record = dict(record)
    if "timestamp" in record and isinstance(record["timestamp"], datetime):
        record["timestamp"] = record["timestamp"].isoformat()
    return record


def serialize_timestamps_bulk(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [serialize_timestamps(r) for r in records]