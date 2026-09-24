"""Regression tests for api.serialization.to_jsonable.

Original bug: GET /api/simulate/{hours} returned 500 ("Object of type Timestamp
is not JSON serializable") because raw pandas records went into a JSON column
and the response.
"""

import json
from datetime import date, datetime
from enum import Enum

import numpy as np
import pandas as pd
import pytest

from api.serialization import serialize_timestamps, serialize_timestamps_bulk, to_jsonable


class Mode(str, Enum):  # same shape as CoolingMode: an Enum that is ALSO a str
    HYBRID = "hybrid"


def _strict_dumps(obj):
    """allow_nan=False: NaN/inf must not survive (Postgres json rejects them)."""
    return json.dumps(obj, allow_nan=False)


class TestToJsonable:
    def test_dataframe_records_with_timestamps_are_serializable(self):
        df = pd.DataFrame([{"timestamp": datetime(2026, 1, 2, 3, 4, 5), "pue": 1.3}] * 3)
        records = df.iloc[::2].to_dict("records")
        assert isinstance(records[0]["timestamp"], pd.Timestamp)
        with pytest.raises(TypeError):
            json.dumps(records)  # the original bug
        out = to_jsonable(records)
        assert out[0]["timestamp"] == "2026-01-02T03:04:05"
        _strict_dumps(out)

    def test_numpy_scalars_become_python(self):
        out = to_jsonable({"f": np.float32(1.5), "i": np.int64(3), "b": np.bool_(True)})
        assert out == {"f": 1.5, "i": 3, "b": True}
        assert type(out["f"]) is float and type(out["i"]) is int and type(out["b"]) is bool

    def test_nan_and_inf_become_none(self):
        out = to_jsonable({"a": float("nan"), "b": np.float64("inf"), "c": -np.inf, "d": np.float32("nan")})
        assert out == {"a": None, "b": None, "c": None, "d": None}
        _strict_dumps(out)

    def test_enum_checked_before_str(self):
        # Mode is a str subclass; a naive isinstance(str) check would return the member itself.
        assert to_jsonable(Mode.HYBRID) == "hybrid"
        assert type(to_jsonable(Mode.HYBRID)) is str

    def test_nat_and_none(self):
        assert to_jsonable(pd.NaT) is None
        assert to_jsonable(None) is None
        assert to_jsonable(np.datetime64("NaT")) is None

    def test_nested_containers_and_key_coercion(self):
        out = to_jsonable({1: (np.float32(2.5), date(2026, 1, 2)), "arr": np.array([1.0, np.nan])})
        assert out == {"1": [2.5, "2026-01-02"], "arr": [1.0, None]}

    def test_unknown_objects_fall_back_to_str(self):
        class Thing:
            def __str__(self):
                return "thing"

        assert to_jsonable(Thing()) == "thing"

    def test_legacy_wrappers_delegate(self):
        rec = {"timestamp": pd.Timestamp("2026-01-01"), "x": np.float64(1.0)}
        assert serialize_timestamps(rec) == {"timestamp": "2026-01-01T00:00:00", "x": 1.0}
        assert serialize_timestamps_bulk([rec]) == [{"timestamp": "2026-01-01T00:00:00", "x": 1.0}]
