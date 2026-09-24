"""Shared response-serialization helpers.

The digital twin and optimizer hand back pandas/numpy-flavoured records
(``pandas.Timestamp``, ``numpy.float64``, ``NaN``, ``Enum`` members...). None of
those are JSON serializable: returning them from a route, or storing them in a
``JSON`` column, raises ``TypeError: Object of type Timestamp is not JSON
serializable`` (a 500). Everything that leaves the process -- HTTP response,
WebSocket frame, JSON DB column -- goes through :func:`to_jsonable` first.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


def to_jsonable(value: Any) -> Any:
    """Recursively convert ``value`` into plain JSON-safe Python objects.

    * ``datetime`` / ``date`` / ``time`` / ``pandas.Timestamp`` -> ISO-8601 string
      (``pandas.NaT`` -> ``None``)
    * numpy scalars -> the equivalent Python scalar; numpy arrays -> lists
    * ``NaN`` / ``+-inf`` (Python or numpy floats) -> ``None`` (JSON has no
      representation for them, and Postgres' ``json`` type rejects ``NaN``)
    * ``Enum`` -> its ``.value`` (checked BEFORE ``str`` because
      ``CoolingMode`` is a ``str`` subclass)
    * dict keys are coerced to ``str``; tuples/sets become lists
    * anything unrecognised falls back to ``str(value)`` rather than raising
    """
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, Decimal):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (datetime, date, time)):  # pandas.Timestamp is a datetime subclass
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, pd.Series):
        return to_jsonable(value.to_dict())
    if isinstance(value, pd.DataFrame):
        return to_jsonable(value.to_dict("records"))
    return str(value)


def serialize_timestamps(record: dict[str, Any]) -> dict[str, Any]:
    """Backwards-compatible wrapper: full JSON-safe conversion of one record."""
    return to_jsonable(record)


def serialize_timestamps_bulk(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backwards-compatible wrapper: full JSON-safe conversion of many records."""
    return to_jsonable(records)
