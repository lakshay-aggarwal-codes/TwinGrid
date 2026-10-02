from __future__ import annotations

import asyncio
import logging
import os
import random
from collections import deque
from datetime import datetime

import numpy as np
from fastapi import WebSocket

from api.serialization import to_jsonable
from api.services.twin_service import get_twin
from database import get_session
from models.db_models import SensorReading
from src.versions import ORIGIN_SIMULATED, PHYSICS_VERSION

logger = logging.getLogger(__name__)

BROADCAST_INTERVAL_SECONDS = 3

# Slowly-drifting live water-stress reading. This feed is deliberately
# independent of the sidebar's What-If sliders (it's the facility's own
# live telemetry, not a preview -- see the WS effect in useSimulation.ts).
# Previously `random.uniform(0, 0.5)` picked a brand-new value every 3s with
# no memory, i.e. real white noise -- not how any live sensor behaves, and
# why the Sustainability tab's number looked broken/nonsensical rather than
# just "a different metric than the slider". Mean-reverting random walk
# instead: moves a little each tick, stays in [0, 0.5].
_water_stress_state = 0.2
_WATER_STRESS_STEP = 0.02


# ---------------------------------------------------------------------------
# Fan-out (T4b). broadcast() only enqueues; one writer task per client does the
# actual send, so a slow or dead client can never delay the tick or any other
# client. Tunables (read when a ConnectionManager is created):
#   BROADCAST_MODE=serial            old behaviour (await each client in turn) -- rollback switch
#   BROADCAST_SEND_TIMEOUT_SECONDS   per-send timeout before a client is dropped (default 2.0)
#   BROADCAST_QUEUE_DEPTH            frames kept per client, newest win (default 1, max 10)
# ---------------------------------------------------------------------------

_DEFAULT_SEND_TIMEOUT_SECONDS = 2.0
_DEFAULT_QUEUE_DEPTH = 1
_MAX_QUEUE_DEPTH = 10
_CLOSE_TIMEOUT_SECONDS = 1.0
_SLOW_CLIENT_CLOSE_CODE = 1013  # "try again later"


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_depth() -> int:
    try:
        value = int(os.getenv("BROADCAST_QUEUE_DEPTH", ""))
    except ValueError:
        return _DEFAULT_QUEUE_DEPTH
    return min(max(value, 1), _MAX_QUEUE_DEPTH)


def _env_mode() -> str:
    return "serial" if os.getenv("BROADCAST_MODE", "").strip().lower() == "serial" else "concurrent"


class _ClientChannel:
    """Bounded outbox for one client: at most ``depth`` frames, newest win."""

    __slots__ = ("websocket", "pending", "wakeup", "task", "dropped_frames")

    def __init__(self, websocket: WebSocket, depth: int) -> None:
        self.websocket = websocket
        self.pending: deque[dict] = deque(maxlen=depth)
        self.wakeup = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.dropped_frames = 0

    def offer(self, payload: dict) -> None:
        if len(self.pending) == self.pending.maxlen:
            self.dropped_frames += 1  # deque discards the oldest frame
        self.pending.append(payload)
        self.wakeup.set()


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts to all of them."""

    def __init__(
        self,
        *,
        send_timeout: float | None = None,
        queue_depth: int | None = None,
        mode: str | None = None,
    ) -> None:
        self._connections: set[WebSocket] = set()
        self._channels: dict[WebSocket, _ClientChannel] = {}
        self._send_timeout = send_timeout or _env_float("BROADCAST_SEND_TIMEOUT_SECONDS", _DEFAULT_SEND_TIMEOUT_SECONDS)
        self._queue_depth = queue_depth or _env_depth()
        self._mode = mode or _env_mode()

    def connect(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)
        # The writer task is started lazily by the first broadcast(), which
        # always runs inside the event loop (connect() itself may not).
        self._channels.setdefault(websocket, _ClientChannel(websocket, self._queue_depth))
        logger.info("WebSocket connected (%d active)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        channel = self._channels.pop(websocket, None)
        if channel is not None and channel.task is not None and not channel.task.done():
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if channel.task is not current:  # a writer evicting its own client must not cancel itself
                channel.task.cancel()
        logger.info("WebSocket disconnected (%d active)", len(self._connections))

    def has_connections(self) -> bool:
        return bool(self._connections)

    async def broadcast(self, payload: dict) -> None:
        """Hand ``payload`` to every client. Never awaits a client (unless
        BROADCAST_MODE=serial) and never raises because of one."""
        if not self._connections:
            return
        if self._mode == "serial":
            await self._broadcast_serial(payload)
            return
        # Iterate a snapshot: connect()/disconnect() can run between iterations.
        for ws in list(self._connections):
            channel = self._channels.get(ws)
            if channel is None:  # added to _connections without connect()
                channel = self._channels.setdefault(ws, _ClientChannel(ws, self._queue_depth))
            channel.offer(payload)
            if channel.task is None or channel.task.done():
                channel.task = asyncio.get_running_loop().create_task(self._run_writer(channel))

    async def _run_writer(self, channel: _ClientChannel) -> None:
        """Dedicated sender for one client. Exits (and evicts the client) on a
        send failure or timeout; exits quietly when cancelled by disconnect()."""
        ws = channel.websocket
        while True:
            await channel.wakeup.wait()
            channel.wakeup.clear()
            while channel.pending:
                frame = channel.pending.popleft()
                try:
                    await asyncio.wait_for(ws.send_json(frame), self._send_timeout)
                except TimeoutError:
                    await self._evict(channel, f"no send progress within {self._send_timeout:g}s (slow client)")
                    return
                except Exception as exc:
                    await self._evict(channel, f"send failed ({type(exc).__name__})")
                    return

    async def _evict(self, channel: _ClientChannel, reason: str) -> None:
        ws = channel.websocket
        logger.warning("Dropping WebSocket client: %s; %d frame(s) skipped", reason, channel.dropped_frames)
        if self._channels.get(ws) is channel:
            self.disconnect(ws)
        try:
            await asyncio.wait_for(ws.close(code=_SLOW_CLIENT_CLOSE_CODE), _CLOSE_TIMEOUT_SECONDS)
        except Exception:
            pass  # best effort: the peer may already be gone or unresponsive

    async def _broadcast_serial(self, payload: dict) -> None:
        """Pre-T4b behaviour, kept for rollback (BROADCAST_MODE=serial)."""
        dead: list[WebSocket] = []
        # Iterate a snapshot: connect()/disconnect() can run while we await a
        # send, and mutating a set during iteration raises RuntimeError.
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def _tick() -> dict:
    """One shared simulation step, used by every connected client."""
    global _water_stress_state
    twin = get_twin()
    hour = datetime.now().hour + datetime.now().minute / 60
    utilisation = float(np.clip(0.4 + 0.5 * np.sin((hour - 6) * np.pi / 12), 0, 1))
    outside_temp = 22 + 5 * np.sin(2 * np.pi * (hour - 14) / 24) + random.uniform(-1, 1)
    _water_stress_state = float(
        np.clip(_water_stress_state + random.uniform(-_WATER_STRESS_STEP, _WATER_STRESS_STEP), 0, 0.5)
    )
    water_stress = _water_stress_state
    action = {
        "utilisation": utilisation,
        "outside_temp_C": outside_temp,
        "water_stress": water_stress,
        "cooling_mode": twin.select_cooling_mode(outside_temp, water_stress),
    }
    state = twin.step(action)
    state_dict = state.to_dict()

    # ONE write per tick, regardless of how many clients are connected --
    # previously this was one write per tick PER CLIENT. Persistence is
    # best-effort: a database outage must never stop the live stream.
    try:
        async with get_session() as session:
            session.add(
                SensorReading.from_state_dict(
                    state_dict, "ws", origin=ORIGIN_SIMULATED, physics_version=PHYSICS_VERSION
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Could not persist live sensor reading -- broadcasting anyway")

    return to_jsonable({**state_dict, "carbon_data_is_real": twin.carbon_data_is_real})


async def run_broadcast_loop() -> None:
    """Runs forever (until cancelled at app shutdown). Started once in
    api/main.py's lifespan, not per-connection."""
    logger.info("Starting live broadcast loop (interval=%ds)", BROADCAST_INTERVAL_SECONDS)
    while True:
        try:
            # No clients -> nobody to stream to, so don't advance the twin or
            # write to the database at all (previously: a row every 3 s, 24/7).
            if manager.has_connections():
                payload = await _tick()
                await manager.broadcast(payload)
        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled")
            raise
        except Exception:
            logger.exception("Error in broadcast tick -- continuing")
        await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
