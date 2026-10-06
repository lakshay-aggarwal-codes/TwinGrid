"""T18: fan-out isolation at scale, the new drop/eviction rules, and the section 8.5 ``ws_*`` signals.

tests/test_ws_fanout.py (T4b) stays the behavioural specification and is not modified; these add what T18 asks
on top of it: 200 clients with one stalled, 1013 after WS_MAX_CONSECUTIVE_DROPS, the WS_* names and mode names.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest

from api import config
from api.middleware.metrics import registry
from api.services.live_broadcast_service import ConnectionManager


class FakeWebSocket:
    def __init__(self, *, stall: bool = False, fail: bool = False):
        self.stall, self.fail = stall, fail
        self.received: list[dict] = []
        self.started = asyncio.Event()
        self.close_codes: list[int] = []

    async def send_json(self, payload):
        self.started.set()
        if self.fail:
            raise ConnectionError("dead")
        if self.stall:
            await asyncio.Event().wait()
        self.received.append(payload)

    async def close(self, code: int = 1000):
        self.close_codes.append(code)


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.002)


def _sample(name: str, labels: dict | None = None) -> float:
    return registry.get_sample_value(name, labels or {}) or 0.0


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (
        "BROADCAST_MODE",
        "BROADCAST_SEND_TIMEOUT_SECONDS",
        "BROADCAST_QUEUE_DEPTH",
        "WS_SEND_TIMEOUT_S",
        "WS_CLIENT_QUEUE_MAX",
        "WS_MAX_CONSECUTIVE_DROPS",
    ):
        monkeypatch.delenv(name, raising=False)


# ----------------------------------------------------------------------------- 200 clients, one stalled
async def _tick_latency(n_healthy: int, with_stalled: bool, rounds: int = 20) -> float:
    """Median seconds from broadcast() start until EVERY healthy client has the frame."""
    manager = ConnectionManager(send_timeout=30.0, queue_depth=1, mode="concurrent")
    healthy = [FakeWebSocket() for _ in range(n_healthy)]
    stalled = FakeWebSocket(stall=True) if with_stalled else None
    for ws in ([stalled] if stalled else []) + healthy:
        manager.connect(ws)
    samples = []
    for seq in range(rounds):
        t0 = time.perf_counter()
        await manager.broadcast({"seq": seq})
        await _until(lambda: all(len(ws.received) == seq + 1 for ws in healthy))
        samples.append(time.perf_counter() - t0)
    for ws in list(manager._connections):
        manager.disconnect(ws)
    return statistics.median(samples)


async def test_two_hundred_clients_one_stalled_tick_time_within_ten_percent():
    """Tick time = broadcast + delivery to every healthy client. Compared with the SAME 199 healthy clients and no
    stalled one. Timing assertions can flake on a loaded machine, so the comparison is retried up to 3 times."""
    ratios = []
    for _ in range(3):
        baseline = await _tick_latency(199, with_stalled=False)
        with_stalled = await _tick_latency(199, with_stalled=True)
        ratios.append(with_stalled / baseline)
        if 0.9 <= ratios[-1] <= 1.1:
            return
    pytest.fail(f"tick time with one stalled client differs from baseline by more than 10%: ratios {ratios}")


async def test_two_hundred_clients_one_stalled_everyone_else_gets_every_frame_in_order():
    manager = ConnectionManager(send_timeout=0.2, queue_depth=1, mode="concurrent")
    stalled = FakeWebSocket(stall=True)
    healthy = [FakeWebSocket() for _ in range(199)]
    for ws in [stalled, *healthy]:
        manager.connect(ws)
    for seq in range(5):
        await manager.broadcast({"seq": seq})
        await _until(lambda: all(len(ws.received) == seq + 1 for ws in healthy))
    assert all([f["seq"] for f in ws.received] == [0, 1, 2, 3, 4] for ws in healthy)
    await _until(lambda: stalled not in manager._connections)  # evicted by the send timeout alone
    assert stalled.close_codes == [1013] and len(manager._connections) == 199


# ----------------------------------------------------------------------------- drop rules and signals
async def test_consecutive_drops_close_the_client_with_1013():
    manager = ConnectionManager(send_timeout=30.0, queue_depth=1, mode="concurrent", max_consecutive_drops=3)
    stalled = FakeWebSocket(stall=True)
    manager.connect(stalled)
    await manager.broadcast({"seq": 0})
    await asyncio.wait_for(stalled.started.wait(), 1)  # frame 0 in flight; queue empty
    for seq in (1, 2, 3, 4):  # 1 queues; 2, 3, 4 each drop the oldest -> 3 consecutive drops
        await manager.broadcast({"seq": seq})
    await _until(lambda: stalled.close_codes == [1013])
    assert stalled not in manager._connections and stalled not in manager._channels


async def test_a_completed_send_resets_the_consecutive_drop_count():
    gate = asyncio.Event()

    class Gated(FakeWebSocket):
        async def send_json(self, payload):
            self.started.set()
            await gate.wait()
            self.received.append(payload)

    manager = ConnectionManager(send_timeout=30.0, queue_depth=1, mode="concurrent", max_consecutive_drops=3)
    ws = Gated()
    manager.connect(ws)
    await manager.broadcast({"seq": 0})
    await asyncio.wait_for(ws.started.wait(), 1)
    for seq in (1, 2, 3):  # 2 drops (< 3)
        await manager.broadcast({"seq": seq})
    assert manager._channels[ws].consecutive_drops == 2
    gate.set()
    await _until(lambda: len(ws.received) == 2)
    assert manager._channels[ws].consecutive_drops == 0 and ws.close_codes == []


async def test_ws_dropped_messages_total_counts_drop_oldest():
    before = _sample("ws_dropped_messages_total")
    manager = ConnectionManager(send_timeout=30.0, queue_depth=1, mode="concurrent")
    ws = FakeWebSocket(stall=True)
    manager.connect(ws)
    await manager.broadcast({"seq": 0})
    await asyncio.wait_for(ws.started.wait(), 1)
    for seq in range(1, 6):  # seq 1 queues, 2..5 each displace the previous: 4 drops
        await manager.broadcast({"seq": seq})
    assert _sample("ws_dropped_messages_total") - before == 4
    assert manager._channels[ws].dropped_frames == 4
    manager.disconnect(ws)


async def test_ws_connections_gauge_tracks_registrations():
    manager = ConnectionManager(mode="concurrent")
    a, b = FakeWebSocket(), FakeWebSocket()
    manager.connect(a)
    manager.connect(b)
    assert _sample("ws_connections") == 2
    manager.disconnect(a)
    assert _sample("ws_connections") == 1
    manager.disconnect(b)
    assert _sample("ws_connections") == 0


async def test_evicted_client_leaves_the_gauge():
    manager = ConnectionManager(send_timeout=0.05, queue_depth=1, mode="concurrent")
    stalled, good = FakeWebSocket(stall=True), FakeWebSocket()
    manager.connect(stalled)
    manager.connect(good)
    await manager.broadcast({"seq": 1})
    await _until(lambda: stalled not in manager._connections)
    assert _sample("ws_connections") == 1


async def test_failed_send_closes_with_1011():
    manager = ConnectionManager(mode="concurrent")
    dead = FakeWebSocket(fail=True)
    manager.connect(dead)
    await manager.broadcast({"seq": 1})
    await _until(lambda: dead.close_codes == [1011])


# ----------------------------------------------------------------------------- names and rollback
async def test_contract_env_names_are_honoured(monkeypatch):
    monkeypatch.setenv("WS_SEND_TIMEOUT_S", "0.7")
    monkeypatch.setenv("WS_CLIENT_QUEUE_MAX", "3")
    monkeypatch.setenv("WS_MAX_CONSECUTIVE_DROPS", "42")
    m = ConnectionManager()
    assert (m._send_timeout, m._queue_depth, m._max_consecutive_drops) == (0.7, 3, 42)


async def test_contract_names_win_over_the_t4b_aliases(monkeypatch):
    monkeypatch.setenv("WS_SEND_TIMEOUT_S", "0.7")
    monkeypatch.setenv("BROADCAST_SEND_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("BROADCAST_QUEUE_DEPTH", "2")
    m = ConnectionManager()
    assert (m._send_timeout, m._queue_depth) == (0.7, 2)  # alias still used where the new name is unset


@pytest.mark.parametrize(
    ("raw", "internal"),
    [("isolated", "concurrent"), ("concurrent", "concurrent"), ("sequential", "serial"), ("serial", "serial")],
)
async def test_broadcast_mode_names(monkeypatch, raw, internal):
    monkeypatch.setenv("BROADCAST_MODE", raw)
    assert ConnectionManager()._mode == internal
    assert ConnectionManager(mode=raw)._mode == internal
    assert config.broadcast_mode() == internal


async def test_unknown_or_unset_mode_is_isolated(monkeypatch):
    monkeypatch.setenv("BROADCAST_MODE", "whatever")
    assert ConnectionManager()._mode == "concurrent"
    monkeypatch.delenv("BROADCAST_MODE")
    assert ConnectionManager()._mode == "concurrent"


async def test_sequential_mode_is_blocked_by_a_stalled_client_isolated_is_not():
    """The rollback (BROADCAST_MODE=sequential) restores the old behaviour, which this documents."""
    for mode, blocked in (("sequential", True), ("isolated", False)):
        manager = ConnectionManager(mode=mode, send_timeout=30.0)
        manager.connect(FakeWebSocket(stall=True))
        manager.connect(FakeWebSocket())
        if blocked:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(manager.broadcast({"seq": 1}), 0.2)
        else:
            await asyncio.wait_for(manager.broadcast({"seq": 1}), 0.2)
        for ws in list(manager._connections):
            manager.disconnect(ws)


def test_queue_max_is_clamped_to_ten_and_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv("WS_CLIENT_QUEUE_MAX", "999")
    assert config.ws_client_queue_max() == 10
    monkeypatch.setenv("WS_CLIENT_QUEUE_MAX", "abc")
    assert config.ws_client_queue_max() == 1
    monkeypatch.setenv("WS_SEND_TIMEOUT_S", "-3")
    assert config.ws_send_timeout_s() == 2.0
