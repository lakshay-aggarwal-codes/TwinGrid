"""/ws/live authentication + the shared broadcast tick."""

import time
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.main import app
from api.services import live_broadcast_service
from api.services.live_broadcast_service import manager
from models.db_models import SensorReading


def _token(role="viewer"):
    import api.auth as auth_module

    return auth_module.create_access_token(1, role)


def _wait_until(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_ws_rejects_invalid_token():
    client = TestClient(app)  # not used as a context manager -> lifespan (DB, broadcast loop) is not started
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/live?token=not-a-token"):
            pass
    assert exc.value.code == 4001


def test_ws_rejects_missing_token():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live"):
            pass


def test_ws_valid_token_registers_and_unregisters():
    client = TestClient(app)
    assert not manager.has_connections()
    with client.websocket_connect(f"/ws/live?token={_token()}"):
        assert _wait_until(manager.has_connections)
    assert _wait_until(lambda: not manager.has_connections())


# ----------------------------------------------------------------------------- _tick
@pytest.fixture
def ws_session(session_maker, monkeypatch):
    @asynccontextmanager
    async def fake_get_session():
        async with session_maker() as s:
            yield s

    monkeypatch.setattr(live_broadcast_service, "get_session", fake_get_session)


async def test_tick_returns_json_safe_payload_and_persists_one_row(ws_session, session_maker):
    payload = await live_broadcast_service._tick()
    assert payload["pue"] >= 1.0 and isinstance(payload["timestamp"], str)
    assert "carbon_data_is_real" in payload
    async with session_maker() as s:
        n = (
            await s.execute(select(func.count()).select_from(SensorReading).where(SensorReading.source == "ws"))
        ).scalar_one()
    assert n == 1


async def test_tick_still_broadcasts_when_db_is_down(monkeypatch):
    @asynccontextmanager
    async def broken_session():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(live_broadcast_service, "get_session", broken_session)
    payload = await live_broadcast_service._tick()
    assert payload["pue"] >= 1.0  # persistence is best-effort; the live stream must survive


async def test_water_stress_random_walk_stays_bounded(ws_session):
    values = []
    for _ in range(40):
        values.append((await live_broadcast_service._tick())["water_stress"])
    assert all(0.0 <= v <= 0.5 for v in values)
    assert max(abs(b - a) for a, b in zip(values, values[1:])) <= live_broadcast_service._WATER_STRESS_STEP + 1e-9
