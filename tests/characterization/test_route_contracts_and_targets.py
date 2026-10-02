"""HTTP-level characterization (legacy behaviours that later tasks change) and strict-xfail
TARGET tests for behaviours the roadmap requires but the code does not yet have.

xfail policy: ``strict=True`` (an unexpected pass fails the suite, forcing the owning task to
remove the marker) and ``raises=AssertionError`` (a fixture/setup error is a hard failure, never a
silent xfail). Verify the failure reasons with:  pytest tests/characterization --runxfail
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from api.main import app
from api.services import anomaly_service, twin_service
from database import get_db
from models.db_models import Alert, SensorReading, SimulationRun
from tests.characterization import golden_support as gs

STATE_PARAMS = {"utilisation": 0.8, "outside_temp": 30, "water_stress": 0.0, "mode": "evaporative"}
WINDOW = json.dumps([[30.0, 3.0, 35.0, 300.0, 50.0]] * 12)
LEAK_MARKER = "SECRET-DB-DETAIL-9f3a"


def target(task_id: str):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=task_id)


# ----------------------------------------------------------------------------- /api/state (T2)
@pytest.mark.legacy_behavior("T2")
async def test_api_state_today_persists_one_api_row_and_advances_shared_twin(
    client, viewer_headers, count_rows, isolated_shared_twin
):
    twin = twin_service.get_twin()
    t0 = twin._time
    r = await client.get("/api/state", params=STATE_PARAMS, headers=viewer_headers)
    assert r.status_code == 200
    assert await count_rows(SensorReading, SensorReading.source == "api") == 1
    assert twin._time == t0 + timedelta(minutes=5)
    assert twin._water_consumed_cumulative_L > 0


@target("T2")
async def test_api_state_is_side_effect_free(client, viewer_headers, count_rows, isolated_shared_twin):
    twin = twin_service.get_twin()
    t0, w0 = twin._time, twin._water_consumed_cumulative_L
    rows0 = await count_rows(SensorReading)
    r = await client.get("/api/state", params=STATE_PARAMS, headers=viewer_headers)
    assert r.status_code == 200
    assert await count_rows(SensorReading) == rows0, "/api/state must not persist rows"
    assert (twin._time, twin._water_consumed_cumulative_L) == (t0, w0), "/api/state must not step the live twin"


async def test_api_whatif_and_benchmark_persist_nothing_and_leave_live_twin_alone(
    client, viewer_headers, count_rows, isolated_shared_twin
):
    twin = twin_service.get_twin()
    t0, w0 = twin._time, twin._water_consumed_cumulative_L
    assert (await client.get("/api/whatif", headers=viewer_headers)).status_code == 200
    assert (await client.get("/api/benchmark", headers=viewer_headers)).status_code == 200
    assert await count_rows(SensorReading) == 0
    assert (twin._time, twin._water_consumed_cumulative_L) == (t0, w0)


@pytest.mark.legacy_behavior("T9-T10")
async def test_api_simulate_get_persists_a_run_and_hourly_rows(client, viewer_headers, count_rows, frozen_env):
    """Contract debt D-1: a GET that writes. Moved to POST only once an owner column exists."""
    r = await client.get("/api/simulate/3", headers=viewer_headers)
    assert r.status_code == 200 and len(r.json()) == 3
    assert await count_rows(SimulationRun) == 1
    assert await count_rows(SensorReading, SensorReading.source == "simulation") == 3


# ----------------------------------------------------------------------------- /healthz (T0b)
class _BrokenSession:
    async def execute(self, *a, **k):
        raise RuntimeError(LEAK_MARKER)


async def _healthz_with_broken_db(client):
    async def broken_db():
        yield _BrokenSession()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = broken_db
    try:
        return await client.get("/healthz")
    finally:
        app.dependency_overrides[get_db] = previous


@pytest.mark.legacy_behavior("T0b")
async def test_healthz_today_echoes_the_raw_exception_text(client):
    r = await _healthz_with_broken_db(client)
    assert r.status_code == 503
    assert r.json()["detail"] == f"Database unreachable: {LEAK_MARKER}"


@target("T0b")
async def test_healthz_503_body_contains_no_raw_exception_text(client):
    r = await _healthz_with_broken_db(client)
    assert r.status_code == 503
    assert LEAK_MARKER not in r.text


async def test_healthz_ok_shape_is_unchanged(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "timestamp", "database"} and body["status"] == "ok"


# ----------------------------------------------------------------------------- anomaly alerts (T3)
def _alerting(monkeypatch):
    result = {
        "score": 9.0,
        "threshold": 1.0,
        "alert": True,
        "type": "thermal_spike",
        "message": "Outlet temperature spike detected",
        "explanation": None,
    }
    monkeypatch.setattr(anomaly_service, "score_recent_data", lambda _raw: result)


async def test_viewer_scoring_call_creates_no_alert(client, viewer_headers, count_rows, monkeypatch):
    _alerting(monkeypatch)
    r = await client.get("/api/anomaly_score", params={"recent_data": WINDOW}, headers=viewer_headers)
    assert r.status_code == 200
    assert await count_rows(Alert) == 0, "alert ownership belongs to the server pipeline, not a viewer's request"


# ----------------------------------------------------------------------------- WS payload provenance (T1a)
def test_ws_payload_contains_origin_and_seq():  # was strict-xfail "T1a"; flipped by T1a
    keys = set(gs.run_ws_ticks()["key_set"])
    assert {"origin", "seq"} <= keys
