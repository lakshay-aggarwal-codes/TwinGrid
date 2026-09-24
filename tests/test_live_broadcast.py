"""
Regression tests for Phase 11: previously each WebSocket client ran its
own independent simulation loop. These tests cover the replacement
ConnectionManager's behaviour in isolation (not a full WS integration
test, which needs a running server).
"""

import asyncio

import pytest

from api.services import live_broadcast_service
from api.services.live_broadcast_service import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.received = []

    async def send_json(self, payload):
        if self.fail:
            raise ConnectionError("simulated dead connection")
        self.received.append(payload)


class TestConnectionManager:
    def test_connect_and_disconnect_tracked(self):
        manager = ConnectionManager()
        ws = FakeWebSocket()
        manager.connect(ws)
        assert ws in manager._connections
        manager.disconnect(ws)
        assert ws not in manager._connections

    @pytest.mark.asyncio
    async def test_broadcast_reaches_all_connected_clients(self):
        manager = ConnectionManager()
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        manager.connect(ws1)
        manager.connect(ws2)
        payload = {"pue": 1.3}
        await manager.broadcast(payload)
        assert ws1.received == [payload]
        assert ws2.received == [payload]

    @pytest.mark.asyncio
    async def test_broadcast_survives_a_dead_connection(self):
        """The specific regression this guards: one client disconnecting
        mid-broadcast must not prevent delivery to the other clients, and
        must not raise out of broadcast()."""
        manager = ConnectionManager()
        good_ws = FakeWebSocket()
        dead_ws = FakeWebSocket(fail=True)
        manager.connect(good_ws)
        manager.connect(dead_ws)

        await manager.broadcast({"pue": 1.4})  # must not raise

        assert good_ws.received == [{"pue": 1.4}]
        assert dead_ws not in manager._connections  # pruned automatically

    @pytest.mark.asyncio
    async def test_broadcast_with_no_clients_is_a_noop(self):
        manager = ConnectionManager()
        await manager.broadcast({"pue": 1.5})  # must not raise


class TestBroadcastLoop:
    """The shared loop must be idle without clients and must survive DB failures."""

    @staticmethod
    async def _run_loop_briefly(seconds: float = 0.12) -> None:
        task = asyncio.create_task(live_broadcast_service.run_broadcast_loop())
        await asyncio.sleep(seconds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_no_clients_means_no_tick_and_no_db_write(self, monkeypatch):
        ticks = []

        async def fake_tick():
            ticks.append(1)
            return {"pue": 1.2}

        monkeypatch.setattr(live_broadcast_service, "_tick", fake_tick)
        monkeypatch.setattr(live_broadcast_service, "BROADCAST_INTERVAL_SECONDS", 0.01)
        monkeypatch.setattr(live_broadcast_service, "manager", ConnectionManager())

        await self._run_loop_briefly()
        assert ticks == []

    @pytest.mark.asyncio
    async def test_ticks_and_broadcasts_when_a_client_is_connected(self, monkeypatch):
        async def fake_tick():
            return {"pue": 1.2}

        manager = ConnectionManager()
        ws = FakeWebSocket()
        manager.connect(ws)
        monkeypatch.setattr(live_broadcast_service, "_tick", fake_tick)
        monkeypatch.setattr(live_broadcast_service, "BROADCAST_INTERVAL_SECONDS", 0.01)
        monkeypatch.setattr(live_broadcast_service, "manager", manager)

        await self._run_loop_briefly()
        assert len(ws.received) >= 2
        assert ws.received[0] == {"pue": 1.2}

    @pytest.mark.asyncio
    async def test_database_failure_does_not_stop_the_stream(self, monkeypatch):
        class BrokenSession:
            async def __aenter__(self):
                raise ConnectionError("database is down")

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(live_broadcast_service, "get_session", lambda: BrokenSession())
        payload = await live_broadcast_service._tick()  # must not raise
        assert "pue" in payload and isinstance(payload["timestamp"], str)
