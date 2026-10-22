"""T1b: every current writer stamps origin='simulated' and the ACTIVE physics_version (``legacy-0`` until physics 1
became the default; the writers stamp whatever ``active_physics_version()`` says, so the tests ask it too)."""

from datetime import datetime

import pytest
from sqlalchemy import select

from api.services import live_broadcast_service, optimization_service
from models.db_models import OptimizationResult, SensorReading, SimulationRun
from src import model_registry
from src.versions import active_physics_version

SUMMARY = {
    "mean_pue": 1.3,
    "mean_wue": 0.5,
    "mean_cooling_power_kw": 80.0,
    "total_water_consumed_L": 1200.0,
    "total_reward": -50.0,
    "safety_violations": 0,
}


@pytest.fixture
def fake_optimizer(monkeypatch):
    """Fake rollout. The returned dict is merged into the summary: a test sets ``model_id`` to play a served policy."""
    served: dict[str, str] = {}

    async def fake_run(alpha, beta, gamma, water_stress, hours):
        # The route stores what the SERVED policy reports in its summary (optimization_routes.py): its physics
        # version and its registry model id. It no longer looks the registry up itself.
        summary = {**SUMMARY, "physics_version": active_physics_version(), **served}
        return [{"pue": 1.3, "timestamp": datetime(2026, 1, 1), "cooling_mode": "hybrid"}], summary

    monkeypatch.setattr(optimization_service, "run_optimization", fake_run)
    return served


async def _all(session_maker, model):
    async with session_maker() as s:
        return (await s.execute(select(model))).scalars().all()


def _physics() -> str:
    return active_physics_version()


async def test_state_is_a_stateless_preview_and_no_longer_a_writer(client, viewer_headers, session_maker):
    # T2: GET /api/state used to persist one stamped row; it is a preview now, so there is nothing to stamp.
    assert (await client.get("/api/state", headers=viewer_headers)).status_code == 200
    assert await _all(session_maker, SensorReading) == []


async def test_simulation_run_and_its_readings_are_stamped(client, operator_headers, session_maker):
    # T14: /api/simulate writes only with persist=true (operator)
    assert (await client.get("/api/simulate/3?persist=true", headers=operator_headers)).status_code == 200
    runs = await _all(session_maker, SimulationRun)
    readings = await _all(session_maker, SensorReading)
    assert [r.physics_version for r in runs] == [_physics()]
    assert len(readings) == 3
    assert {(r.origin, r.physics_version) for r in readings} == {("simulated", _physics())}


async def test_live_tick_reading_is_stamped(session_maker, monkeypatch):
    monkeypatch.setattr(live_broadcast_service, "get_session", lambda: session_maker())
    payload = await live_broadcast_service._tick()
    assert "pue" in payload
    rows = await _all(session_maker, SensorReading)
    assert len(rows) == 1 and rows[0].source == "ws"
    assert (rows[0].origin, rows[0].physics_version) == ("simulated", _physics())


async def test_optimization_result_gets_physics_and_model_version_from_the_served_policy(
    client, operator_headers, fake_optimizer, session_maker
):
    fake_optimizer["model_id"] = "20260927T143232Z"
    assert (await client.post("/api/optimize", json={}, headers=operator_headers)).status_code == 200
    saved = (await _all(session_maker, OptimizationResult))[0]
    assert saved.physics_version == _physics()
    assert saved.model_version == "20260927T143232Z"


async def test_optimization_model_version_is_null_when_the_policy_reports_none(
    client, operator_headers, fake_optimizer, session_maker
):
    assert (await client.post("/api/optimize", json={}, headers=operator_headers)).status_code == 200
    saved = (await _all(session_maker, OptimizationResult))[0]
    assert (saved.physics_version, saved.model_version) == (_physics(), None)


async def test_registry_failure_does_not_break_the_write(
    client, operator_headers, fake_optimizer, session_maker, monkeypatch
):
    def boom(name):
        raise OSError("registry unreadable")

    monkeypatch.setattr(model_registry, "latest", boom)
    assert (await client.post("/api/optimize", json={}, headers=operator_headers)).status_code == 200
    assert (await _all(session_maker, OptimizationResult))[0].model_version is None
