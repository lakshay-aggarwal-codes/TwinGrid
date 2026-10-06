"""Supervision of long-running background loops (T18, roadmap section 8.5).

A supervised loop is "call ``tick()`` every ``interval_s``". The supervisor adds what a bare ``while True`` lacks:

* Each tick runs under ``wait_for(TICK_TIMEOUT_S)``. A tick that raises, or hangs past the timeout, counts as a
  crash of the loop: it is restarted after an exponential backoff (1 s, 2 s, 4 s ... capped at 30 s; the backoff
  resets once a tick succeeds) and ``background_loop_restarts_total{loop}`` is incremented.
* Every successful tick refreshes a heartbeat (and ``background_loop_last_success_timestamp{loop}``).
  ``heartbeat_fresh`` is what ``/readyz`` reads: fresh means younger than ``3 x interval + 5 s``.
* Restarts are capped per window (default 10 per 600 s). Past the cap the supervisor GIVES UP, logs at CRITICAL
  and leaves the loop stopped, so a persistent crash cannot hide behind endless restarts: readiness fails.
* ``shutdown`` cancels every loop and waits for them under a deadline (default 10 s), then logs.

Process-local state only; nothing here survives a restart or spans workers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from api import config
from api.middleware.metrics import BACKGROUND_LOOP_LAST_SUCCESS, BACKGROUND_LOOP_RESTARTS

logger = logging.getLogger(__name__)

BACKOFF_INITIAL_S = 1.0
BACKOFF_MAX_S = 30.0


def backoff_s(
    consecutive_failures: int, *, initial: float = BACKOFF_INITIAL_S, maximum: float = BACKOFF_MAX_S
) -> float:
    """Delay before restart number ``consecutive_failures`` (0-based): initial, 2x, 4x ... capped at ``maximum``."""
    return min(maximum, initial * (2 ** max(0, consecutive_failures)))


@dataclass
class LoopState:
    name: str
    interval_s: float
    tick_timeout_s: float
    started_at: float
    last_success: float | None = None
    restarts: int = 0
    consecutive_failures: int = 0
    gave_up: bool = False
    running: bool = False
    last_error: str | None = None
    restart_times: deque[float] = field(default_factory=deque)

    def snapshot(self) -> dict[str, object]:
        return {
            "loop": self.name,
            "running": self.running,
            "gave_up": self.gave_up,
            "restarts": self.restarts,
            "last_success": self.last_success,
            "last_error": self.last_error,
        }


class Supervisor:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        backoff_initial_s: float = BACKOFF_INITIAL_S,
        backoff_max_s: float = BACKOFF_MAX_S,
    ) -> None:
        self._clock = clock
        self._backoff_initial = backoff_initial_s
        self._backoff_max = backoff_max_s
        self._states: dict[str, LoopState] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------ lifecycle
    def start(
        self,
        name: str,
        tick: Callable[[], Awaitable[object]],
        *,
        interval_s: float,
        tick_timeout_s: float | None = None,
    ) -> asyncio.Task[None]:
        """Start supervising ``tick`` as loop ``name`` (must be called with a running event loop)."""
        existing = self._tasks.get(name)
        if existing is not None and not existing.done():
            raise RuntimeError(f"loop {name!r} is already supervised")
        state = LoopState(
            name=name,
            interval_s=interval_s,
            tick_timeout_s=tick_timeout_s if tick_timeout_s is not None else config.tick_timeout_s(),
            started_at=self._clock(),
        )
        self._states[name] = state
        task = asyncio.create_task(self._supervise(state, tick), name=f"supervised:{name}")
        self._tasks[name] = task
        return task

    async def shutdown(self, deadline_s: float | None = None) -> None:
        """Cancel every loop and wait up to ``deadline_s`` (default SHUTDOWN_DEADLINE_S) for them to end."""
        deadline = deadline_s if deadline_s is not None else config.shutdown_deadline_s()
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=deadline)
            if pending:
                logger.error(
                    "Shutdown deadline (%.1fs) hit; still running: %s", deadline, sorted(t.get_name() for t in pending)
                )
            else:
                logger.info("Background loops stopped: %s", sorted(t.get_name() for t in tasks))
        for state in self._states.values():
            state.running = False

    # ------------------------------------------------------------------ introspection
    def state(self, name: str) -> LoopState | None:
        return self._states.get(name)

    def states(self) -> list[LoopState]:
        return list(self._states.values())

    def heartbeat_age_s(self, name: str, now: float | None = None) -> float | None:
        state = self._states.get(name)
        if state is None:
            return None
        now = self._clock() if now is None else now
        return now - (state.last_success if state.last_success is not None else state.started_at)

    def heartbeat_fresh(self, name: str, now: float | None = None) -> bool:
        """True iff the loop is supervised, has not been given up on, and its last success (or, before the first
        one, its start) is younger than 3 x interval + 5 s."""
        state = self._states.get(name)
        if state is None or state.gave_up:
            return False
        task = self._tasks.get(name)
        if task is None or task.done():
            return False
        age = self.heartbeat_age_s(name, now)
        return age is not None and age < 3 * state.interval_s + 5.0

    # ------------------------------------------------------------------ the supervision loop
    async def _supervise(self, state: LoopState, tick: Callable[[], Awaitable[object]]) -> None:
        state.running = True
        try:
            while True:
                try:
                    await self._run_ticks(state, tick)
                except asyncio.CancelledError:
                    logger.info("Loop %s cancelled", state.name)
                    raise
                except Exception as exc:  # includes asyncio.TimeoutError from a hung tick
                    if not await self._on_crash(state, exc):
                        return
        finally:
            state.running = False

    async def _run_ticks(self, state: LoopState, tick: Callable[[], Awaitable[object]]) -> None:
        while True:
            await asyncio.wait_for(tick(), state.tick_timeout_s)
            now = self._clock()
            state.last_success = now
            state.consecutive_failures = 0
            BACKGROUND_LOOP_LAST_SUCCESS.labels(loop=state.name).set(now)
            await asyncio.sleep(state.interval_s)

    async def _on_crash(self, state: LoopState, exc: Exception) -> bool:
        """Record a crash. Returns False if the supervisor gives up (restart cap exceeded)."""
        now = self._clock()
        reason = "tick timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
        state.last_error = reason  # the type only; the message stays in the log
        state.restarts += 1
        BACKGROUND_LOOP_RESTARTS.labels(loop=state.name).inc()
        window = config.supervisor_restart_window_s()
        state.restart_times.append(now)
        while state.restart_times and now - state.restart_times[0] > window:
            state.restart_times.popleft()
        cap = config.supervisor_max_restarts()
        if len(state.restart_times) > cap:
            state.gave_up = True
            logger.critical(
                "Loop %s crashed %d times within %.0fs (cap %d): NOT restarting it again; /readyz now fails",
                state.name,
                len(state.restart_times),
                window,
                cap,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return False
        delay = backoff_s(state.consecutive_failures, initial=self._backoff_initial, maximum=self._backoff_max)
        state.consecutive_failures += 1
        logger.error(
            "Loop %s crashed (%s); restart #%d in %.1fs",
            state.name,
            reason,
            state.restarts,
            delay,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        await asyncio.sleep(delay)
        return True


supervisor = Supervisor()
