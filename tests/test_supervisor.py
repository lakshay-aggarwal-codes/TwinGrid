"""T18: supervised background loops (api/supervisor.py), roadmap section 8.5 rows
``background_loop_restarts_total{loop}``, ``background_loop_last_success_timestamp{loop}`` and the
"Broadcast loop" crash / hang rows. No app, no network; real (tiny) timings, fake wall clock where freshness matters.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from api import supervisor as supervisor_module
from api.middleware.metrics import registry
from api.supervisor import Supervisor, backoff_s


def _restarts(loop: str) -> float:
    return registry.get_sample_value("background_loop_restarts_total", {"loop": loop}) or 0.0


def _last_success(loop: str) -> float | None:
    return registry.get_sample_value("background_loop_last_success_timestamp", {"loop": loop})


async def _until(predicate, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.002)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("SUPERVISOR_MAX_RESTARTS", "SUPERVISOR_RESTART_WINDOW_S", "TICK_TIMEOUT_S", "SHUTDOWN_DEADLINE_S"):
        monkeypatch.delenv(name, raising=False)


def test_backoff_doubles_from_1_to_30_seconds():
    assert [backoff_s(n) for n in range(8)] == [1, 2, 4, 8, 16, 30, 30, 30]


async def test_crashed_loop_is_restarted_and_counted():
    sup = Supervisor(backoff_initial_s=0.01, backoff_max_s=0.02)
    calls = {"n": 0}

    async def tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")

    sup.start("t-crash", tick, interval_s=0.01, tick_timeout_s=1)
    await _until(lambda: calls["n"] >= 4)
    state = sup.state("t-crash")
    assert state.restarts == 1 and _restarts("t-crash") == 1
    assert state.last_success is not None and state.running and not state.gave_up
    assert state.last_error == "RuntimeError"  # the type only; the message stays in the log
    assert _last_success("t-crash") == pytest.approx(state.last_success)
    assert sup.heartbeat_fresh("t-crash")
    await sup.shutdown(1)


async def test_backoff_grows_between_consecutive_crashes_and_resets_after_a_success(monkeypatch):
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(supervisor_module.asyncio, "sleep", fake_sleep)
    sup = Supervisor(backoff_initial_s=1.0, backoff_max_s=30.0)
    outcomes = iter([False, False, False, True, False])  # crash x3, success, crash, then fine

    async def tick():
        try:
            if not next(outcomes):
                raise ValueError("x")
        except StopIteration:
            await real_sleep(0.001)

    sup.start("t-backoff", tick, interval_s=0.0, tick_timeout_s=1)
    await _until(lambda: sup.state("t-backoff").restarts == 4)
    await sup.shutdown(1)
    restart_delays = [d for d in delays if d >= 1.0]
    assert restart_delays[:4] == [1.0, 2.0, 4.0, 1.0]  # grows 1 -> 2 -> 4, then resets after the success


async def test_hung_tick_is_cancelled_by_the_timeout_and_the_loop_restarts():
    sup = Supervisor(backoff_initial_s=0.01, backoff_max_s=0.02)
    cancelled = asyncio.Event()
    calls = {"n": 0}

    async def tick():
        calls["n"] += 1
        if calls["n"] == 1:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    sup.start("t-hang", tick, interval_s=0.01, tick_timeout_s=0.05)
    await _until(lambda: sup.state("t-hang").last_success is not None)
    assert cancelled.is_set()
    state = sup.state("t-hang")
    assert state.restarts == 1 and state.last_error == "tick timeout"
    await sup.shutdown(1)


async def test_persistent_crash_is_not_masked_supervisor_gives_up_after_the_cap(monkeypatch, caplog):
    monkeypatch.setenv("SUPERVISOR_MAX_RESTARTS", "3")
    sup = Supervisor(backoff_initial_s=0.001, backoff_max_s=0.002)

    async def tick():
        raise RuntimeError("always")

    with caplog.at_level(logging.CRITICAL):
        task = sup.start("t-giveup", tick, interval_s=0.001, tick_timeout_s=1)
        await asyncio.wait_for(task, 3)
    state = sup.state("t-giveup")
    assert state.gave_up and not state.running
    assert state.restarts == 4  # the 4th crash exceeds a cap of 3 and is not restarted
    assert _restarts("t-giveup") == 4
    assert not sup.heartbeat_fresh("t-giveup")  # readiness will fail
    assert any("NOT restarting" in r.getMessage() for r in caplog.records)


async def test_restarts_outside_the_window_do_not_count_toward_the_cap(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_MAX_RESTARTS", "2")
    monkeypatch.setenv("SUPERVISOR_RESTART_WINDOW_S", "10")
    now = {"t": 1000.0}
    sup = Supervisor(clock=lambda: now["t"], backoff_initial_s=0.001, backoff_max_s=0.001)
    crashes = {"n": 0}

    async def tick():
        crashes["n"] += 1
        if crashes["n"] in (1, 2, 4, 5):
            now["t"] += 100 if crashes["n"] in (2, 4) else 0  # jump past the window between some crashes
            raise RuntimeError("x")

    sup.start("t-window", tick, interval_s=0.001, tick_timeout_s=1)
    await _until(lambda: crashes["n"] >= 8)
    assert not sup.state("t-window").gave_up
    await sup.shutdown(1)


async def test_heartbeat_goes_stale_after_three_intervals_plus_five_seconds():
    now = {"t": 5000.0}
    sup = Supervisor(clock=lambda: now["t"])

    async def tick():
        return None

    sup.start("t-stale", tick, interval_s=3.0, tick_timeout_s=1)
    await _until(lambda: sup.state("t-stale").last_success is not None)
    last = sup.state("t-stale").last_success
    assert sup.heartbeat_fresh("t-stale", now=last + 3 * 3.0 + 4.9)
    assert not sup.heartbeat_fresh("t-stale", now=last + 3 * 3.0 + 5.1)
    await sup.shutdown(1)


async def test_unknown_loop_is_not_fresh_and_double_start_is_refused():
    sup = Supervisor()
    assert not sup.heartbeat_fresh("nope") and sup.heartbeat_age_s("nope") is None

    async def tick():
        return None

    sup.start("t-dup", tick, interval_s=1)
    with pytest.raises(RuntimeError):
        sup.start("t-dup", tick, interval_s=1)
    await sup.shutdown(1)


async def test_controlled_shutdown_cancels_every_loop_and_logs(caplog):
    sup = Supervisor()

    async def tick():
        return None

    tasks = [sup.start(f"t-stop-{i}", tick, interval_s=0.5) for i in range(3)]
    await asyncio.sleep(0.01)
    with caplog.at_level(logging.INFO):
        await sup.shutdown(deadline_s=2)
    assert all(t.done() for t in tasks)
    assert all(not s.running for s in sup.states())
    assert any("Background loops stopped" in r.getMessage() for r in caplog.records)


async def test_shutdown_deadline_is_enforced_for_a_loop_that_will_not_stop(caplog):
    sup = Supervisor()
    release = asyncio.Event()

    async def tick():
        while not release.is_set():  # swallows cancellation: a misbehaving tick
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                continue

    sup.start("t-stubborn", tick, interval_s=0.5, tick_timeout_s=60)
    await asyncio.sleep(0.02)
    with caplog.at_level(logging.ERROR):
        await asyncio.wait_for(sup.shutdown(deadline_s=0.1), 2)  # returns at the deadline instead of hanging
    assert any("Shutdown deadline" in r.getMessage() for r in caplog.records)
    release.set()
    await asyncio.sleep(0.05)
