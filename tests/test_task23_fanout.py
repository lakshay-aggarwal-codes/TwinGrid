"""Task 23: realtime fan-out -- serialise once, slow-client drop policy, per-user connection caps.

Fake sockets only (no network, no database). Complements tests/test_ws_fanout.py (T4b) and
tests/test_runtime_fanout.py (T18); the Task 6 ticket flow is exercised in tests/test_task6_security.py and is not
touched by this change.
"""

import asyncio
import json

import pytest

from api.services import live_broadcast_service as svc
from api.services.live_broadcast_service import ConnectionLimitExceeded, ConnectionManager


async def _until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.002)


class TextSocket:
    """Like a Starlette WebSocket: offers send_text (what the shared frame uses) and send_json."""

    def __init__(self, *, stall: bool = False):
        self.stall = stall
        self.texts: list[str] = []
        self.jsons: list[dict] = []
        self.close_codes: list[int] = []

    async def send_text(self, text: str):
        if self.stall:
            await asyncio.Event().wait()
        self.texts.append(text)

    async def send_json(self, payload):  # must NOT be used while send_text is available
        self.jsons.append(payload)

    async def close(self, code: int = 1000):
        self.close_codes.append(code)


class JsonOnlySocket:
    """The older fake shape: only send_json."""

    def __init__(self):
        self.received: list[dict] = []

    async def send_json(self, payload):
        self.received.append(payload)

    async def close(self, code: int = 1000):
        pass


def _manager(**kw) -> ConnectionManager:
    return ConnectionManager(**{"send_timeout": 0.1, "queue_depth": 2, "mode": "concurrent", **kw})


# ----------------------------------------------------------------------------- serialise once


async def test_payload_is_serialised_once_for_many_clients(monkeypatch):
    calls = []
    real = svc._encode_once

    def counting(payload):
        calls.append(payload)
        return real(payload)

    monkeypatch.setattr(svc, "_encode_once", counting)
    manager = _manager()
    sockets = [TextSocket() for _ in range(25)]
    for ws in sockets:
        manager.connect(ws)
    await manager.broadcast({"seq": 1, "pue": 1.2})
    await _until(lambda: all(ws.texts for ws in sockets))
    assert len(calls) == 1  # one encode per broadcast, not one per client
    assert all(ws.jsons == [] for ws in sockets)


async def test_every_client_gets_the_identical_text_frame():
    manager = _manager()
    a, b = TextSocket(), TextSocket()
    manager.connect(a)
    manager.connect(b)
    payload = {"seq": 7, "origin": "simulated", "note": "é", "nested": {"x": [1, 2.5, None]}}
    await manager.broadcast(payload)
    await _until(lambda: a.texts and b.texts)
    assert a.texts == b.texts
    assert json.loads(a.texts[0]) == payload
    assert " " not in a.texts[0].replace("é", "")  # compact separators, like Starlette's send_json


async def test_socket_without_send_text_still_gets_the_payload_via_send_json():
    manager = _manager()
    legacy = JsonOnlySocket()
    manager.connect(legacy)
    await manager.broadcast({"seq": 1})
    await _until(lambda: legacy.received == [{"seq": 1}])


async def test_unencodable_payload_falls_back_to_send_json_and_is_not_swallowed():
    manager = _manager()
    ws = TextSocket()
    manager.connect(ws)
    await manager.broadcast({"seq": 1, "bad": float("nan")})  # allow_nan=False -> no text; send_json decides
    await _until(lambda: len(ws.jsons) == 1)
    assert ws.texts == []


async def test_serial_mode_also_uses_the_shared_text_frame():
    manager = _manager(mode="serial")
    a, b = TextSocket(), TextSocket()
    manager.connect(a)
    manager.connect(b)
    await manager.broadcast({"seq": 1})
    assert a.texts == b.texts and len(a.texts) == 1


async def test_queued_payloads_stay_plain_dicts_for_inspection():
    manager = _manager(queue_depth=1, send_timeout=5.0)
    gate = TextSocket(stall=True)
    manager.connect(gate)
    await manager.broadcast({"seq": 1})
    await manager.broadcast({"seq": 2})
    await manager.broadcast({"seq": 3})
    assert isinstance(manager._channels[gate].pending[0], dict)
    assert [f["seq"] for f in manager._channels[gate].pending] == [3]


# ----------------------------------------------------------------------------- slow-client drop policy


async def test_slow_client_is_dropped_and_closed_without_delaying_healthy_clients():
    manager = _manager(send_timeout=0.05)
    slow, healthy = TextSocket(stall=True), TextSocket()
    manager.connect(slow)
    manager.connect(healthy)
    await manager.broadcast({"seq": 1})
    await _until(lambda: slow not in manager._connections)
    await _until(lambda: slow.close_codes == [svc.WS_CLOSE_SLOW_CLIENT])
    assert healthy in manager._connections
    await manager.broadcast({"seq": 2})
    await _until(lambda: [json.loads(t)["seq"] for t in healthy.texts] == [1, 2])


async def test_client_that_never_drains_is_evicted_after_consecutive_drops():
    manager = _manager(send_timeout=30.0, queue_depth=1, max_consecutive_drops=3)
    stuck = TextSocket(stall=True)
    manager.connect(stuck)
    for seq in range(1, 8):
        await manager.broadcast({"seq": seq})
        await asyncio.sleep(0)
    await _until(lambda: stuck not in manager._connections)
    await _until(lambda: stuck.close_codes == [svc.WS_CLOSE_SLOW_CLIENT])


# ----------------------------------------------------------------------------- per-user / global caps


def test_per_user_cap_rejects_the_extra_socket_and_registers_nothing():
    manager = _manager()
    first, second, third = TextSocket(), TextSocket(), TextSocket()
    manager.connect(first, "u1", max_per_user=2)
    manager.connect(second, "u1", max_per_user=2)
    with pytest.raises(ConnectionLimitExceeded) as exc:
        manager.connect(third, "u1", max_per_user=2)
    assert exc.value.scope == "user"
    assert third not in manager._connections and third not in manager._owners
    assert manager._per_user == {"u1": 2}


def test_per_user_cap_is_independent_per_user():
    manager = _manager()
    manager.connect(TextSocket(), "u1", max_per_user=1)
    manager.connect(TextSocket(), "u2", max_per_user=1)  # a different user is not affected
    with pytest.raises(ConnectionLimitExceeded):
        manager.connect(TextSocket(), "u1", max_per_user=1)


def test_global_cap_rejects_with_global_scope():
    manager = _manager()
    manager.connect(TextSocket(), "u1", max_global=2)
    manager.connect(TextSocket(), "u2", max_global=2)
    with pytest.raises(ConnectionLimitExceeded) as exc:
        manager.connect(TextSocket(), "u3", max_global=2)
    assert exc.value.scope == "global"


def test_disconnect_frees_a_slot_and_is_idempotent():
    manager = _manager()
    a = TextSocket()
    manager.connect(a, "u1", max_per_user=1)
    manager.disconnect(a)
    manager.disconnect(a)
    assert manager._per_user == {}
    manager.connect(TextSocket(), "u1", max_per_user=1)  # the slot is free again


async def test_evicted_slow_client_keeps_its_slot_until_its_handler_disconnects():
    manager = _manager(send_timeout=0.05)
    slow = TextSocket(stall=True)
    manager.connect(slow, "u1", max_per_user=1)
    await manager.broadcast({"seq": 1})
    await _until(lambda: slow not in manager._connections)
    with pytest.raises(ConnectionLimitExceeded):  # the route's finally has not run yet
        manager.connect(TextSocket(), "u1", max_per_user=1)
    manager.disconnect(slow)  # what the route's `finally` does
    manager.connect(TextSocket(), "u1", max_per_user=1)
