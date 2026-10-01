"""T2: GET /api/state is a stateless preview.

It must not (a) write to the database, (b) touch the shared live twin, or
(c) change what the next live WebSocket tick produces. Response shape/params are
covered in test_routes_state_whatif.py.
"""

import random
from contextlib import asynccontextmanager
from datetime import datetime

import pytest

from api.services import live_broadcast_service, twin_service
from models.db_models import SensorReading
from src.digital_twin import DigitalTwin

FIXED_START = datetime(2025, 6, 1, 12, 0, 0)
N_CALLS = 7
PARAM_SETS = [
    {"utilisation": 0.9, "outside_temp": 40, "water_stress": 0.0, "mode": "evaporative"},
    {"utilisation": 0.1, "outside_temp": -5, "water_stress": 1.0, "mode": "auto"},
    {"utilisation": 0.5, "outside_temp": 25, "water_stress": 0.5, "mode": "hybrid"},
]


@pytest.fixture
def fresh_shared_twin(monkeypatch):
    """Replace the process-global live twin with a fixed-start one (restored after the test)."""
    twin = DigitalTwin(start_time=FIXED_START)
    monkeypatch.setattr(twin_service, "_twin", twin)
    monkeypatch.setattr(live_broadcast_service, "_water_stress_state", 0.2)
    return twin


def _fingerprint(twin: DigitalTwin) -> dict:
    return {
        "time": twin._time,
        "water_cum": twin._water_consumed_cumulative_L,
        "inlet": twin._inlet_temp_C,
        "outlet": twin._outlet_temp_C,
        "chilled_applied": twin._applied_chilled_water_temp_C,
        "state": twin._state.to_dict(),
    }


async def _hit_state(client, headers, n=N_CALLS):
    for i in range(n):
        r = await client.get("/api/state", params=PARAM_SETS[i % len(PARAM_SETS)], headers=headers)
        assert r.status_code == 200, r.text


async def test_state_writes_no_rows_of_any_source(client, viewer_headers, count_rows):
    await _hit_state(client, viewer_headers)
    assert await count_rows(SensorReading) == 0


async def test_state_never_touches_the_shared_twin_object(client, viewer_headers, monkeypatch):
    def boom():
        raise AssertionError("/api/state must not obtain the shared live twin")

    monkeypatch.setattr(twin_service, "get_twin", boom)
    await _hit_state(client, viewer_headers)


async def test_state_leaves_shared_twin_state_and_counters_unchanged(client, viewer_headers, fresh_shared_twin):
    # Give the live twin non-trivial history first, so "unchanged" is meaningful.
    for _ in range(3):
        twin_service.compute_state(0.8, 30.0, 0.2, "evaporative")
    assert fresh_shared_twin._water_consumed_cumulative_L > 0
    before = _fingerprint(fresh_shared_twin)

    await _hit_state(client, viewer_headers)

    assert _fingerprint(fresh_shared_twin) == before
    assert twin_service.get_twin() is fresh_shared_twin


async def test_state_preview_is_independent_of_live_history(client, viewer_headers, fresh_shared_twin):
    """Same inputs -> same preview, regardless of how far the live twin has advanced."""
    params = PARAM_SETS[0]
    first = (await client.get("/api/state", params=params, headers=viewer_headers)).json()
    for _ in range(5):
        twin_service.compute_state(0.9, 38.0, 0.1, "evaporative")  # advance the live twin
    second = (await client.get("/api/state", params=params, headers=viewer_headers)).json()
    # Each preview is a single fresh step: cumulative water must not accumulate across calls or with live history.
    assert second["water_consumed_L"] == pytest.approx(first["water_consumed_L"])
    assert second["pue"] == pytest.approx(first["pue"])


async def _next_tick_payload(monkeypatch, session_maker, before_tick=None):
    @asynccontextmanager
    async def fake_get_session():
        async with session_maker() as s:
            yield s

    class _FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 6, 1, 15, 30)

    monkeypatch.setattr(live_broadcast_service, "get_session", fake_get_session)
    monkeypatch.setattr(live_broadcast_service, "datetime", _FixedNow)
    twin_service._twin = DigitalTwin(start_time=FIXED_START)
    live_broadcast_service._water_stress_state = 0.2
    random.seed(1234)
    if before_tick is not None:
        await before_tick()
    return await live_broadcast_service._tick()


async def test_next_live_tick_is_identical_with_or_without_state_calls(
    client, viewer_headers, session_maker, monkeypatch
):
    monkeypatch.setattr(twin_service, "_twin", None)  # restored by monkeypatch on teardown
    monkeypatch.setattr(live_broadcast_service, "_water_stress_state", 0.2)

    control = await _next_tick_payload(monkeypatch, session_maker)

    async def hammer():
        await _hit_state(client, viewer_headers)

    with_calls = await _next_tick_payload(monkeypatch, session_maker, before_tick=hammer)

    assert with_calls == control
