"""T1b: every current writer stamps origin='simulated' and physics_version='legacy-0'."""

from datetime import datetime

import pytest
from sqlalchemy import select

from api.services import live_broadcast_service, optimization_service
from models.db_models import OptimizationResult, SensorReading, SimulationRun
from src import model_registry

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
    async def fake_run(alpha, beta, gamma, water_stress, hours):
        return [{"pue": 1.3, "timestamp": datetime(2026, 1, 1), "cooling_mode": "hybrid"}], dict(SUMMARY)

    monkeypatch.setattr(optimization_service, "run_optimization", fake_run)


async def _all(session_maker, model):
    async with session_maker() as s:
        return (await s.execute(select(model))).scalars().all()


async def test_state_reading_is_stamped(client, viewer_headers, session_maker):
    assert (await client.get("/api/state", headers=viewer_headers)).status_code == 200
    rows = await _all(session_maker, SensorReading)
    assert len(rows) == 1
    assert (rows[0].origin, rows[0].physics_version) == ("simulated", "legacy-0")


async def test_simulation_run_and_its_readings_are_stamped(client, viewer_headers, session_maker):
    assert (await client.get("/api/simulate/3", headers=viewer_headers)).status_code == 200
    runs = await _all(session_maker, SimulationRun)
    readings = await _all(session_maker, SensorReading)
    assert [r.physics_version for r in runs] == ["legacy-0"]
    assert len(readings) == 3
    assert {(r.origin, r.physics_version) for r in readings} == {("simulated", "legacy-0")}


async def test_live_tick_reading_is_stamped(session_maker, monkeypatch):
    monkeypatch.setattr(live_broadcast_service, "get_session", lambda: session_maker())
    payload = await live_broadcast_service._tick()
    assert "pue" in payload
    rows = await _all(session_maker, SensorReading)
    assert len(rows) == 1 and rows[0].source == "ws"
    assert (rows[0].origin, rows[0].physics_version) == ("simulated", "legacy-0")


async def test_optimization_result_gets_physics_and_registry_model_version(
    client, operator_headers, fake_optimizer, session_maker, monkeypatch
):
    monkeypatch.setattr(model_registry, "latest", lambda name: {"name": name, "version": "20260927T143232Z"})
    assert (await client.post("/api/optimize", json={}, headers=operator_headers)).status_code == 200
    saved = (await _all(session_maker, OptimizationResult))[0]
    assert saved.physics_version == "legacy-0"
    assert saved.model_version == "20260927T143232Z"


async def test_optimization_model_version_is_null_without_a_registry_entry(
    client, operator_headers, fake_optimizer, session_maker, monkeypatch
):
    monkeypatch.setattr(model_registry, "latest", lambda name: None)
    assert (await client.post("/api/optimize", json={}, headers=operator_headers)).status_code == 200
    saved = (await _all(session_maker, OptimizationResult))[0]
    assert (saved.physics_version, saved.model_version) == ("legacy-0", None)


async def test_registry_failure_does_not_break_the_write(
    client, operator_headers, fake_optimizer, session_maker, monkeypatch
):
    def boom(name):
        raise OSError("registry unreadable")

    monkeypatch.setattr(model_registry, "latest", boom)
    assert (await client.post("/api/optimize", json={}, headers=operator_headers)).status_code == 200
    assert (await _all(session_maker, OptimizationResult))[0].model_version is None
