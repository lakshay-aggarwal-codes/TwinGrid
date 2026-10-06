from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from datetime import datetime, timezone

import numpy as np
from fastapi import WebSocket

from api import config
from api.middleware.metrics import WS_CONNECTIONS, WS_DROPPED_MESSAGES
from api.serialization import to_jsonable
from api.services import anomaly_service, telemetry_window
from api.services.twin_service import get_twin
from database import get_session
from models.db_models import SensorReading
from src.digital_twin import INTERVAL_MINUTES

logger = logging.getLogger(__name__)

BROADCAST_INTERVAL_SECONDS = 3

# --- Live payload provenance (T1a, additive) --------------------------------
# WS_SCHEMA_VERSION: version of the additive provenance fields below.
# WS_ORIGIN: every value this loop emits comes from the physics simulator
#   (sine-wave utilisation, random-walk weather); nothing is measured.
# WS_SIM_TIME_SCALE: NOMINAL simulated seconds advanced per wall second --
#   one twin step is INTERVAL_MINUTES of simulated time per tick, one tick per
#   BROADCAST_INTERVAL_SECONDS of wall time (5*60/3 = 100). Derived from
#   constants, not measured; the live driver is NOT corrected to real dt here
#   (that is T7), so this documents the existing ~100x clock instead of fixing it.
WS_SCHEMA_VERSION = 1
WS_ORIGIN = "simulated"
WS_SIM_TIME_SCALE = (INTERVAL_MINUTES * 60) / BROADCAST_INTERVAL_SECONDS

# Strictly +1 per tick per process (first tick is 1). Resets on process restart.
_tick_seq = 0

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


class ConnectionLimitExceeded(Exception):
    """Raised by ``ConnectionManager.connect`` when a connection cap is reached.

    ``scope`` is ``"user"`` (per-user cap) or ``"global"`` (total cap).
    """

    def __init__(self, scope: str) -> None:
        if scope not in ("user", "global"):
            raise ValueError(f"scope must be 'user' or 'global', not {scope!r}")
        super().__init__(f"{scope} connection limit reached")
        self.scope = scope


WS_CLOSE_TRY_AGAIN_LATER = 1013  # slow / stalled client evicted
WS_CLOSE_INTERNAL_ERROR = 1011  # send failed
_CLOSE_TIMEOUT_S = 1.0


class _Channel:
    """Per-connection delivery state: a bounded frame queue and (in isolated mode) its writer task."""

    __slots__ = ("ws", "queue", "task", "dropped_frames", "consecutive_drops", "evicting")

    def __init__(self, ws: WebSocket, depth: int) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=depth)
        self.task: asyncio.Task | None = None
        self.dropped_frames = 0
        self.consecutive_drops = 0
        self.evicting = False

    @property
    def pending(self) -> list[dict]:
        """Frames waiting to be sent, oldest first (a snapshot; ``asyncio.Queue`` has no public iterator)."""
        return list(self.queue._queue)  # type: ignore[attr-defined]


class ConnectionManager:
    """Tracks active WebSocket connections and fans frames out to them (T4b / T18).

    ``mode="concurrent"`` (BROADCAST_MODE=isolated, the default): every connection has its own bounded queue and
    writer task. ``broadcast()`` only enqueues, so its cost does not depend on any client. A full queue drops its
    OLDEST frame (latest state wins; counted in ``ws_dropped_messages_total``); a send that exceeds
    ``send_timeout`` or raises evicts that client alone (close 1013 / 1011); a client that has had
    ``max_consecutive_drops`` frames dropped without one completed send is closed with 1013.

    ``mode="serial"`` (BROADCAST_MODE=sequential, the rollback) is the original behaviour: ``broadcast()`` awaits
    each client in turn with no timeout, so one stalled client blocks all the others.
    """

    def __init__(
        self,
        *,
        send_timeout: float | None = None,
        queue_depth: int | None = None,
        mode: str | None = None,
        max_consecutive_drops: int | None = None,
    ) -> None:
        self._send_timeout = send_timeout if send_timeout is not None else config.ws_send_timeout_s()
        self._queue_depth = queue_depth if queue_depth is not None else config.ws_client_queue_max()
        self._max_consecutive_drops = (
            max_consecutive_drops if max_consecutive_drops is not None else config.ws_max_consecutive_drops()
        )
        if mode is None:
            self._mode = config.broadcast_mode()
        else:
            self._mode = {"isolated": "concurrent", "sequential": "serial"}.get(mode, mode)
        self._connections: set[WebSocket] = set()
        self._channels: dict[WebSocket, _Channel] = {}
        self._background: set[asyncio.Task] = set()  # strong refs to fire-and-forget eviction tasks
        # Cap bookkeeping. A socket stays counted here until disconnect(), even if broadcast()
        # has already evicted it from ``_connections`` after a failed send.
        self._owners: dict[WebSocket, str] = {}
        self._per_user: dict[str, int] = {}

    # ------------------------------------------------------------------ registration
    def connect(
        self,
        websocket: WebSocket,
        user_id: str | None = None,
        *,
        max_per_user: int | None = None,
        max_global: int | None = None,
    ) -> None:
        """Register ``websocket``. With caps given, raises ConnectionLimitExceeded (registering nothing)
        when the user already has ``max_per_user`` sockets or ``max_global`` sockets are registered.
        Synchronous, so check-and-register is atomic with respect to the event loop."""
        if user_id is not None:
            if max_per_user is not None and self._per_user.get(user_id, 0) >= max_per_user:
                raise ConnectionLimitExceeded("user")
            if max_global is not None and len(self._owners) >= max_global:
                raise ConnectionLimitExceeded("global")
            if websocket not in self._owners:
                self._owners[websocket] = user_id
                self._per_user[user_id] = self._per_user.get(user_id, 0) + 1
        self._connections.add(websocket)
        self._channels.setdefault(websocket, _Channel(websocket, self._queue_depth))
        WS_CONNECTIONS.set(len(self._connections))
        logger.info("WebSocket connected (%d active)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Idempotent; safe for a socket that was never registered. Cancels its writer task."""
        self._connections.discard(websocket)
        channel = self._channels.pop(websocket, None)
        if channel is not None and channel.task is not None and not channel.task.done():
            channel.task.cancel()
        user_id = self._owners.pop(websocket, None)
        if user_id is not None:
            remaining = self._per_user.get(user_id, 0) - 1
            if remaining > 0:
                self._per_user[user_id] = remaining
            else:
                self._per_user.pop(user_id, None)
        WS_CONNECTIONS.set(len(self._connections))
        logger.info("WebSocket disconnected (%d active)", len(self._connections))

    def has_connections(self) -> bool:
        return bool(self._connections)

    # ------------------------------------------------------------------ fan-out
    async def broadcast(self, payload: dict) -> None:
        if not self._connections:
            return
        if self._mode == "serial":
            await self._broadcast_serial(payload)
            return
        # Isolated: enqueue only. Iterate a snapshot: connect()/disconnect() may run while we work.
        for ws in list(self._connections):
            channel = self._channels.get(ws)
            if channel is None:
                continue
            if channel.task is None or channel.task.done():
                channel.task = asyncio.create_task(self._writer(channel), name="ws-writer")
            self._enqueue(channel, payload)

    def _enqueue(self, channel: _Channel, payload: dict) -> None:
        if channel.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                channel.queue.get_nowait()  # drop the OLDEST frame: the newest state wins
            channel.dropped_frames += 1
            channel.consecutive_drops += 1
            WS_DROPPED_MESSAGES.inc()
        channel.queue.put_nowait(payload)
        if channel.consecutive_drops >= self._max_consecutive_drops and not channel.evicting:
            channel.evicting = True
            logger.warning("Closing a WebSocket client after %d consecutive dropped frames", channel.consecutive_drops)
            task = asyncio.get_running_loop().create_task(
                self._evict(channel, WS_CLOSE_TRY_AGAIN_LATER, from_writer=False)
            )
            self._background.add(task)
            task.add_done_callback(self._background.discard)

    async def _writer(self, channel: _Channel) -> None:
        """Delivers this client's queued frames, one at a time, each under the send timeout."""
        ws = channel.ws
        try:
            while True:
                frame = await channel.queue.get()
                try:
                    await asyncio.wait_for(ws.send_json(frame), self._send_timeout)
                except asyncio.TimeoutError:
                    logger.warning("WebSocket send exceeded %.2fs; evicting that client", self._send_timeout)
                    await self._evict(channel, WS_CLOSE_TRY_AGAIN_LATER, from_writer=True)
                    return
                except Exception:
                    logger.info("WebSocket send failed; evicting that client", exc_info=True)
                    await self._evict(channel, WS_CLOSE_INTERNAL_ERROR, from_writer=True)
                    return
                channel.consecutive_drops = 0
        except asyncio.CancelledError:
            raise

    async def _evict(self, channel: _Channel, code: int, *, from_writer: bool) -> None:
        """Remove ONE client from fan-out and close it (best effort). Cap bookkeeping stays until disconnect()."""
        ws = channel.ws
        self._connections.discard(ws)
        if self._channels.get(ws) is channel:
            del self._channels[ws]
        WS_CONNECTIONS.set(len(self._connections))
        if channel.task is not None and not channel.task.done() and not from_writer:
            channel.task.cancel()
        close = getattr(ws, "close", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(close(code=code), _CLOSE_TIMEOUT_S)

    async def _broadcast_serial(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)
            self._channels.pop(ws, None)
        if dead:
            WS_CONNECTIONS.set(len(self._connections))


manager = ConnectionManager()


async def _tick() -> dict:
    """One shared simulation step, used by every connected client."""
    global _water_stress_state, _tick_seq
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
    reading_id: int | None = None
    try:
        async with get_session() as session:
            reading = SensorReading.from_state_dict(state_dict, "ws")
            session.add(reading)
            await session.flush()  # assigns reading.id; the anomaly alert links to it (T3)
            reading_id = reading.id
            await session.commit()
    except Exception:
        logger.exception("Could not persist live sensor reading -- broadcasting anyway")

    # T1a: additive provenance/time fields. Every pre-existing key and value is
    # unchanged. They are added to the BROADCAST payload only -- not to
    # state_dict above, so what is persisted is unchanged.
    #   sim_time   = the twin's own clock (same value as the existing
    #                "timestamp" key). It is SIMULATED time, not event time.
    #   ts_ingest  = wall clock (aware UTC) when this tick was assembled; the
    #                client derives staleness from its own receive time, not this.
    #   interval_s = nominal WALL seconds between ticks.
    _tick_seq += 1
    provenance = {
        "schema_version": WS_SCHEMA_VERSION,
        "origin": WS_ORIGIN,
        "seq": _tick_seq,
        "ts_ingest": datetime.fromtimestamp(time.time(), tz=timezone.utc),
        "sim_time": state_dict["timestamp"],
        "sim_time_scale": WS_SIM_TIME_SCALE,
        "interval_s": BROADCAST_INTERVAL_SECONDS,
    }
    ts_ingest_iso = provenance["ts_ingest"].isoformat()

    # T3: server-owned anomaly scoring, ONCE per tick (not per client). The window is filled from
    # what the server itself just produced; the pipeline scores it in a worker thread, fails closed,
    # and owns alert creation. The result rides the payload as ``anomaly_status`` -- a NEW key,
    # because the pre-existing ``anomaly`` key (the twin's own 0/1 flag) must stay unchanged.
    anomaly_status: dict | None = None
    try:
        telemetry_window.get_window_provider().append(
            telemetry_window.sample_from_state(state_dict, seq=_tick_seq, ts_ingest=ts_ingest_iso, origin=WS_ORIGIN)
        )
        anomaly_status = await anomaly_service.get_pipeline().process(
            session_factory=get_session, sensor_reading_id=reading_id
        )
    except Exception:
        logger.exception("Anomaly pipeline failed -- reporting status=error, broadcasting anyway")
        anomaly_service.ANOMALY_SCORING_ERRORS.inc()
        anomaly_status = {
            "status": anomaly_service.STATUS_ERROR,
            "message": "Anomaly pipeline failure",
            "detector_id": anomaly_service.DETECTOR_ID,
            "trained_on": anomaly_service.TRAINED_ON,
        }
    return to_jsonable(
        {**state_dict, "carbon_data_is_real": twin.carbon_data_is_real, **provenance, "anomaly_status": anomaly_status}
    )


BROADCAST_LOOP_NAME = "broadcast"


async def broadcast_once() -> None:
    """ONE iteration of the live loop: tick + fan-out, or nothing when nobody is connected.

    This is the unit the supervisor (api/supervisor.py) runs under ``wait_for(TICK_TIMEOUT_S)``. An idle iteration
    (no clients) still counts as a success, so the heartbeat stays fresh while nobody is watching. Exceptions are
    NOT swallowed here: the supervisor counts them, backs off and restarts the loop.
    """
    # No clients -> nobody to stream to, so don't advance the twin or write to the database at all
    # (previously: a row every 3 s, 24/7).
    if manager.has_connections():
        payload = await _tick()
        await manager.broadcast(payload)


async def run_broadcast_loop() -> None:
    """UNSUPERVISED runner (kept for tests and ad-hoc use): ``broadcast_once`` forever, logging and continuing on
    errors. The application starts ``broadcast_once`` under api.supervisor instead (api/main.py lifespan)."""
    logger.info("Starting live broadcast loop (interval=%ss)", BROADCAST_INTERVAL_SECONDS)
    while True:
        try:
            await broadcast_once()
        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled")
            raise
        except Exception:
            logger.exception("Error in broadcast tick -- continuing")
        await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
