"""WebSocket payload shape (``_tick``) and ``ConnectionManager`` behaviour with fake sockets."""

from __future__ import annotations

import asyncio

import pytest

from api.services.live_broadcast_service import ConnectionManager
from tests.characterization import golden_support as gs


def _golden():
    return gs.load_golden("ws_tick_sequence")["data"]


def test_tick_payload_frozen_keys_and_values_match_golden():
    """Additive-safe: every frozen key keeps its value; later tasks may ADD keys (T1a)."""
    actual = gs.run_ws_ticks()
    expected = _golden()
    assert len(actual["payloads"]) == len(expected["payloads"]) == gs.TICKS
    for i, (a, e) in enumerate(zip(actual["payloads"], expected["payloads"])):
        gs.assert_frozen_subset(a, e, f"$.payloads[{i}]")


def test_tick_payload_key_set_is_superset_of_frozen_key_set():
    assert set(gs.run_ws_ticks()["key_set"]) >= set(_golden()["key_set"])


def test_tick_payload_value_types_unchanged_for_frozen_keys():
    actual = gs.run_ws_ticks()["value_types"]
    for key, type_name in _golden()["value_types"].items():
        assert actual[key] == type_name, key


def test_tick_payload_is_plain_json_types():
    for payload in _golden()["payloads"]:
        for key, value in payload.items():
            assert value is None or isinstance(value, (str, int, float, bool)), key


def test_tick_persists_exactly_one_sensor_reading_per_tick_with_source_ws():
    persisted = _golden()["persistence_per_run"]
    assert persisted["commits"] == gs.TICKS
    assert [r["source"] for r in persisted["rows_added"]] == ["ws"] * gs.TICKS
    assert {r["class"] for r in persisted["rows_added"]} == {"SensorReading"}


def test_tick_swallows_persistence_failure_and_still_returns_payload():
    import api.services.live_broadcast_service as lbs

    class Exploding:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    async def go():
        from unittest import mock

        with gs.live_tick_environment():
            with mock.patch.object(lbs, "get_session", lambda: Exploding()):
                return await lbs._tick()

    payload = asyncio.run(go())
    assert "pue" in payload


# ----------------------------------------------------------------------------- ConnectionManager
class FakeSocket:
    def __init__(self, fail=False, gate: asyncio.Event | None = None):
        self.fail, self.gate, self.received = fail, gate, []

    async def send_json(self, payload):
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise ConnectionError("dead")
        self.received.append(payload)


async def test_broadcast_with_no_connections_is_a_noop():
    await ConnectionManager().broadcast({"x": 1})


async def test_broadcast_delivers_same_payload_to_every_client():
    m, a, b = ConnectionManager(), FakeSocket(), FakeSocket()
    m.connect(a)
    m.connect(b)
    await m.broadcast({"pue": 1.3})
    assert a.received == b.received == [{"pue": 1.3}]


async def test_broadcast_drops_failed_clients_and_keeps_good_ones():
    m, good, dead = ConnectionManager(), FakeSocket(), FakeSocket(fail=True)
    m.connect(good)
    m.connect(dead)
    await m.broadcast({"n": 1})
    assert good.received == [{"n": 1}]
    assert dead not in m._connections and good in m._connections


def test_connect_is_idempotent_and_has_no_connection_cap_today():
    m = ConnectionManager()
    s = FakeSocket()
    m.connect(s)
    m.connect(s)
    assert len(m._connections) == 1
    for _ in range(500):
        m.connect(FakeSocket())
    assert len(m._connections) == 501 and m.has_connections()


def test_disconnect_of_unknown_socket_is_safe():
    ConnectionManager().disconnect(FakeSocket())


@pytest.mark.legacy_behavior("T4b")
async def test_broadcast_does_not_complete_while_any_client_is_stalled():
    """Sends are awaited sequentially with no timeout: one stalled client holds the whole fan-out.
    (Which client is visited first is set-order dependent, so only completion is asserted.)"""
    gate = asyncio.Event()
    m, stalled, normal = ConnectionManager(), FakeSocket(gate=gate), FakeSocket()
    m.connect(stalled)
    m.connect(normal)
    task = asyncio.ensure_future(m.broadcast({"n": 1}))
    done, pending = await asyncio.wait({task}, timeout=0.1)
    assert not done and pending == {task}
    gate.set()
    await asyncio.wait_for(task, timeout=2)
    assert stalled.received == normal.received == [{"n": 1}]
