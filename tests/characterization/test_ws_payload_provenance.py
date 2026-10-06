"""T1a: additive provenance/time fields on the live WebSocket payload.

Acceptance (roadmap T1a): T0 payload keys are a subset of the new key set with identical values
(see test_ws_and_manager_contract.py); ``origin == "simulated"``; ``seq`` consecutive; ``ts_ingest``
within 5 s of wall time and non-decreasing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest import mock

import pytest

import api.services.live_broadcast_service as lbs
from api.serialization import to_jsonable
from tests.characterization import golden_support as gs

NEW_KEYS = {"schema_version", "origin", "seq", "ts_ingest", "sim_time", "sim_time_scale", "interval_s"}


# T23 (roadmap 13.6/13.7): labels that say what the carbon and water-stress numbers are. Additive; no legacy key changes.
T23_KEYS = {
    "carbon_semantic",
    "carbon_is_fallback",
    "carbon_aggregation",
    "water_stress_scenario",
    "water_stress_kind",
    "water_stress_baseline",
    "water_stress_baseline_meta",
}


def _ticks(n: int = 5) -> list[dict]:
    async def go():
        with gs.live_tick_environment():
            return [await lbs._tick() for _ in range(n)]

    return asyncio.run(go())


def test_payload_gains_exactly_the_documented_keys():
    legacy = set(gs.load_golden("ws_tick_sequence")["data"]["key_set"])
    now = set(_ticks(1)[0])
    assert now - legacy == NEW_KEYS | {"anomaly_status"} | T23_KEYS  # anomaly_status: T3; carbon/water labels: T23
    assert legacy <= now


def test_static_fields():
    for p in _ticks(3):
        assert p["schema_version"] == 1
        assert p["origin"] == "simulated"
        assert p["interval_s"] == lbs.BROADCAST_INTERVAL_SECONDS == 3
        assert p["sim_time_scale"] == pytest.approx(100.0)
        assert isinstance(p["interval_s"], int) and isinstance(p["seq"], int)


def test_sim_time_scale_is_derived_from_constants_not_measured():
    from src.digital_twin import INTERVAL_MINUTES

    assert lbs.WS_SIM_TIME_SCALE == INTERVAL_MINUTES * 60 / lbs.BROADCAST_INTERVAL_SECONDS


def test_seq_is_strictly_plus_one_per_tick():
    seqs = [p["seq"] for p in _ticks(6)]
    assert seqs == [1, 2, 3, 4, 5, 6]


def test_seq_continues_across_calls_within_a_process():
    async def go():
        with gs.live_tick_environment():
            a = await lbs._tick()
            b = await lbs._tick()
            return a["seq"], b["seq"]

    a, b = asyncio.run(go())
    assert b == a + 1


def test_ts_ingest_is_aware_utc_from_the_single_clock_and_non_decreasing():
    """T12: ts_ingest is one read of src.timeutil.utc_now() per tick (frozen by the harness)."""
    payloads = _ticks(5)
    stamps = [datetime.fromisoformat(p["ts_ingest"]) for p in payloads]
    for ts in stamps:
        assert ts.tzinfo is not None and ts.utcoffset() == timedelta(0)
        assert ts == gs.FIXED_NOW_UTC
    assert stamps == sorted(stamps)


def test_ts_ingest_is_the_wall_clock_and_does_not_follow_the_simulated_clock():
    """T12: ts_ingest and the twin's default start come from the same clock (frozen here); sim_time
    then advances on its own by the step, so the two diverge after the first tick."""
    ps = _ticks(2)
    ts = [datetime.fromisoformat(p["ts_ingest"]) for p in ps]
    sim = [datetime.fromisoformat(p["sim_time"]) for p in ps]
    assert ts[0] == ts[1] == gs.FIXED_NOW_UTC
    assert sim[0] == gs.FIXED_NOW_UTC + timedelta(minutes=5)
    assert sim[1] > sim[0] and sim[1] != ts[1]


def test_sim_time_is_the_twins_own_timestamp_and_not_the_wall_clock():
    for p in _ticks(3):
        assert p["sim_time"] == p["timestamp"]
        assert p["sim_time"] != p["ts_ingest"]


def test_sim_time_advances_by_the_twin_step_per_tick():
    ps = _ticks(3)
    t = [datetime.fromisoformat(p["sim_time"]) for p in ps]
    assert t[1] - t[0] == t[2] - t[1] == timedelta(minutes=5)


def test_provenance_fields_are_not_persisted_with_the_sensor_reading():
    """Additive on the wire only: the persisted SensorReading is built from the unchanged state dict."""

    async def go():
        with gs.live_tick_environment() as session:
            await lbs._tick()
            return session.added

    added = asyncio.run(go())
    assert len(added) == 1 and added[0].source == "ws"
    cols = {c.name for c in type(added[0]).__table__.columns}
    assert not (NEW_KEYS & cols)


def test_seq_still_increments_when_persistence_fails():
    class Exploding:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    async def go():
        with gs.live_tick_environment():
            with mock.patch.object(lbs, "get_session", lambda: Exploding()):
                return [(await lbs._tick())["seq"] for _ in range(2)]

    assert asyncio.run(go()) == [1, 2]


def test_payload_is_json_serialisable_plain_types():
    import json

    for p in _ticks(2):
        assert json.loads(json.dumps(p, allow_nan=False)) == p
        assert to_jsonable(p) == p
