"""T4b: broadcast fan-out isolation (bounded per-client queue, dedicated writer,
send timeout, slow-client eviction, failure isolation, BROADCAST_MODE=serial).

Fake sockets only -- no network. Timings are deliberately loose; the benchmark
at the bottom records numbers (visible with `pytest -s`) and only gates the
50-client case.
"""

import asyncio
import statistics
import time

import pytest

from api.services.live_broadcast_service import ConnectionManager


async def _until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.002)


class FakeWebSocket:
    """Healthy by default; can stall (never completes a send) or fail."""

    def __init__(self, *, stall: bool = False, fail: bool = False, gate: asyncio.Event | None = None):
        self.stall, self.fail, self.gate = stall, fail, gate
        self.received: list[dict] = []
        self.started = asyncio.Event()
        self.close_codes: list[int] = []

    async def send_json(self, payload):
        self.started.set()
        if self.fail:
            raise ConnectionError("simulated dead connection")
        if self.stall:
            await asyncio.Event().wait()  # never returns; only a timeout/cancel ends it
        if self.gate is not None:
            await self.gate.wait()
        self.received.append(payload)

    async def close(self, code: int = 1000):
        self.close_codes.append(code)


def _manager(**kw) -> ConnectionManager:
    return ConnectionManager(**{"send_timeout": 0.1, "queue_depth": 1, "mode": "concurrent", **kw})


# ----------------------------------------------------------------------------- core behaviour


async def test_broadcast_returns_without_waiting_for_a_stalled_client():
    manager = _manager(send_timeout=5.0)
    stalled, healthy = FakeWebSocket(stall=True), FakeWebSocket()
    manager.connect(stalled)
    manager.connect(healthy)
    t0 = time.perf_counter()
    await manager.broadcast({"seq": 1})
    assert time.perf_counter() - t0 < 0.25  # not 5 s
    await _until(lambda: healthy.received == [{"seq": 1}])


async def test_stalled_client_is_dropped_after_the_timeout_and_closed():
    manager = _manager(send_timeout=0.05)
    stalled, healthy = FakeWebSocket(stall=True), FakeWebSocket()
    manager.connect(stalled)
    manager.connect(healthy)
    await manager.broadcast({"seq": 1})
    await _until(lambda: stalled not in manager._connections)
    assert healthy in manager._connections
    await _until(lambda: stalled.close_codes == [1013])
    assert stalled not in manager._channels


async def test_failing_client_is_isolated_and_removed():
    manager = _manager()
    dead, good = FakeWebSocket(fail=True), FakeWebSocket()
    manager.connect(dead)
    manager.connect(good)
    await manager.broadcast({"seq": 1})  # must not raise
    await _until(lambda: dead not in manager._connections and good.received)
    await manager.broadcast({"seq": 2})
    await _until(lambda: len(good.received) == 2)
    assert [f["seq"] for f in good.received] == [1, 2]


async def test_client_without_close_method_is_still_evicted():
    class NoClose:
        async def send_json(self, payload):
            raise ConnectionError

    manager = _manager()
    ws = NoClose()
    manager.connect(ws)
    await manager.broadcast({"x": 1})
    await _until(lambda: ws not in manager._connections)


async def test_latest_state_wins_for_a_slow_but_alive_client():
    gate = asyncio.Event()
    slow = FakeWebSocket(gate=gate)
    manager = _manager(send_timeout=5.0, queue_depth=1)
    manager.connect(slow)
    await manager.broadcast({"seq": 1})
    await asyncio.wait_for(slow.started.wait(), 1)  # frame 1 is in flight, queue empty
    await manager.broadcast({"seq": 2})
    await manager.broadcast({"seq": 3})  # replaces seq 2
    assert [f["seq"] for f in manager._channels[slow].pending] == [3]
    assert manager._channels[slow].dropped_frames == 1
    gate.set()
    await _until(lambda: len(slow.received) == 2)
    assert [f["seq"] for f in slow.received] == [1, 3]  # gap (2) is normal


async def test_queue_depth_two_keeps_the_two_newest_frames():
    gate = asyncio.Event()
    slow = FakeWebSocket(gate=gate)
    manager = _manager(send_timeout=5.0, queue_depth=2)
    manager.connect(slow)
    await manager.broadcast({"seq": 1})
    await asyncio.wait_for(slow.started.wait(), 1)
    for seq in (2, 3, 4):
        await manager.broadcast({"seq": seq})
    gate.set()
    await _until(lambda: len(slow.received) == 3)
    assert [f["seq"] for f in slow.received] == [1, 3, 4]


async def test_memory_stays_bounded_for_a_stalled_client():
    manager = _manager(send_timeout=30.0, queue_depth=2)
    stalled = FakeWebSocket(stall=True)
    manager.connect(stalled)
    for seq in range(2000):
        await manager.broadcast({"seq": seq})
        if seq == 0:
            await asyncio.wait_for(stalled.started.wait(), 1)
    assert len(manager._channels[stalled].pending) <= 2
    manager.disconnect(stalled)


async def test_disconnect_cancels_the_writer_task_and_is_idempotent():
    manager = _manager(send_timeout=30.0)
    ws = FakeWebSocket(stall=True)
    manager.connect(ws)
    await manager.broadcast({"seq": 1})
    await asyncio.wait_for(ws.started.wait(), 1)
    task = manager._channels[ws].task
    manager.disconnect(ws)
    manager.disconnect(ws)  # second call is harmless
    await asyncio.sleep(0.01)
    assert task.cancelled() or task.done()
    assert not manager.has_connections()


async def test_reconnected_socket_gets_a_fresh_channel():
    manager = _manager()
    ws = FakeWebSocket()
    manager.connect(ws)
    await manager.broadcast({"seq": 1})
    await _until(lambda: ws.received)
    manager.disconnect(ws)
    manager.connect(ws)
    await manager.broadcast({"seq": 2})
    await _until(lambda: len(ws.received) == 2)


# ----------------------------------------------------------------------------- acceptance: 1 stalled + 50 healthy


async def test_one_stalled_and_fifty_healthy_clients():
    manager = _manager(send_timeout=0.2)
    stalled = FakeWebSocket(stall=True)
    healthy = [FakeWebSocket() for _ in range(50)]
    for ws in [stalled, *healthy]:
        manager.connect(ws)

    ticks, durations = 5, []
    for seq in range(ticks):
        t0 = time.perf_counter()
        await manager.broadcast({"seq": seq})
        durations.append(time.perf_counter() - t0)
        await asyncio.sleep(0.02)  # stands in for the tick period

    await _until(lambda: all(len(ws.received) == ticks for ws in healthy))
    assert all([f["seq"] for f in ws.received] == list(range(ticks)) for ws in healthy)
    assert max(durations) < 0.1  # broadcast() cost is independent of the stalled client
    await _until(lambda: stalled not in manager._connections)  # dropped after the timeout
    assert len(manager._connections) == 50


# ----------------------------------------------------------------------------- serial rollback


async def test_serial_mode_keeps_the_old_awaited_behaviour():
    manager = ConnectionManager(mode="serial")
    good, dead = FakeWebSocket(), FakeWebSocket(fail=True)
    manager.connect(good)
    manager.connect(dead)
    await manager.broadcast({"seq": 1})
    assert good.received == [{"seq": 1}]  # delivered before broadcast() returned
    assert dead not in manager._connections  # pruned synchronously
    assert all(c.task is None for c in manager._channels.values())  # no writer tasks in serial mode


async def test_env_flag_selects_serial_mode(monkeypatch):
    monkeypatch.setenv("BROADCAST_MODE", "serial")
    assert ConnectionManager()._mode == "serial"
    monkeypatch.setenv("BROADCAST_MODE", "anything-else")
    assert ConnectionManager()._mode == "concurrent"
    monkeypatch.delenv("BROADCAST_MODE")
    assert ConnectionManager()._mode == "concurrent"


def test_env_tunables_and_bad_values(monkeypatch):
    monkeypatch.setenv("BROADCAST_SEND_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("BROADCAST_QUEUE_DEPTH", "2")
    m = ConnectionManager()
    assert (m._send_timeout, m._queue_depth) == (0.5, 2)
    monkeypatch.setenv("BROADCAST_SEND_TIMEOUT_SECONDS", "-1")
    monkeypatch.setenv("BROADCAST_QUEUE_DEPTH", "999")
    m = ConnectionManager()
    assert (m._send_timeout, m._queue_depth) == (2.0, 10)
    monkeypatch.setenv("BROADCAST_SEND_TIMEOUT_SECONDS", "x")
    monkeypatch.setenv("BROADCAST_QUEUE_DEPTH", "x")
    m = ConnectionManager()
    assert (m._send_timeout, m._queue_depth) == (2.0, 1)


# ----------------------------------------------------------------------------- benchmark (recorded; only 50 gated)


async def _measure(mode: str, n_healthy: int, ticks: int = 5):
    manager = ConnectionManager(send_timeout=0.5, queue_depth=1, mode=mode)
    clients = [FakeWebSocket(stall=True)] + [FakeWebSocket() for _ in range(n_healthy)]
    for ws in clients:
        manager.connect(ws)
    durations = []
    t_start = time.perf_counter()
    for seq in range(ticks):
        t0 = time.perf_counter()
        # serial mode awaits the stalled client forever (no timeout there) -> cap the call
        await asyncio.wait_for(manager.broadcast({"seq": seq}), timeout=1.0 if mode == "serial" else None)
        durations.append(time.perf_counter() - t0)
        await asyncio.sleep(0.01)
    healthy = clients[1:]
    await _until(lambda: all(len(ws.received) == ticks for ws in healthy), timeout=30)
    return durations, time.perf_counter() - t_start


@pytest.mark.parametrize("n_healthy", [10, 50, 1000])
async def test_fanout_benchmark_concurrent_mode(n_healthy, record_property):
    durations, total = await _measure("concurrent", n_healthy)
    median_ms, worst_ms = statistics.median(durations) * 1000, max(durations) * 1000
    record_property("broadcast_median_ms", round(median_ms, 3))
    record_property("broadcast_worst_ms", round(worst_ms, 3))
    print(
        f"[T4b benchmark] concurrent, 1 stalled + {n_healthy} healthy: broadcast() median {median_ms:.2f} ms, "
        f"worst {worst_ms:.2f} ms; all healthy delivered 5/5 in {total * 1000:.0f} ms total"
    )
    if n_healthy <= 50:
        assert worst_ms < 100


async def test_serial_mode_is_blocked_by_a_stalled_client_for_contrast():
    """Documents the problem T4b fixes: in serial mode one stalled client blocks broadcast()."""
    with pytest.raises(asyncio.TimeoutError):
        await _measure("serial", 10)
