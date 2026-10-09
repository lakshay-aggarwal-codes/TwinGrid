from __future__ import annotations

import asyncio
import logging
import os
import random
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from api import config
from api.middleware.metrics import WS_CONNECTIONS, WS_DROPPED_MESSAGES
from api.serialization import to_jsonable
from api.services import anomaly_service, telemetry_window
from api.services.twin_service import get_twin
from database import get_session
from models.db_models import SensorReading
from src.carbon_provider import load_carbon_signal
from src.digital_twin import INTERVAL_MINUTES
from src.ingestion.water_stress_aqueduct import WATER_STRESS_KIND_SCENARIO, baseline_meta, load_country_baseline
from src.timeutil import to_site_local, utc_now
from src.versions import PHYSICS_V1

logger = logging.getLogger(__name__)

BROADCAST_INTERVAL_SECONDS = 3
# Name under which api/main.py registers the loop with the supervisor; /readyz reads the same name.
BROADCAST_LOOP_NAME = "broadcast"

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

# --- T23 labels (roadmap sections 13.6, 13.7) ----------------------------------
# AQUEDUCT_COUNTRY: the country whose ANNUAL Aqueduct baseline index is shown as context. Country-level only.
AQUEDUCT_COUNTRY_ENV = "AQUEDUCT_COUNTRY"
DEFAULT_AQUEDUCT_COUNTRY = "India"
_label_cache: dict | None = None


def _labels() -> dict:
    """Carbon and water-stress labels, computed once per process (files do not change while serving)."""
    global _label_cache
    if _label_cache is None:
        sig = load_carbon_signal()
        country = os.getenv(AQUEDUCT_COUNTRY_ENV, DEFAULT_AQUEDUCT_COUNTRY)
        try:
            base = load_country_baseline(country, temporal="annual")
            value, meta = base.value, base.meta
        except Exception:  # a broken optional file must not stop the live stream
            logger.exception("Aqueduct baseline unavailable")
            value, meta = None, baseline_meta(country=country, available=False, reason="load error")
        _label_cache = {
            "carbon_semantic": sig.semantic,
            "carbon_is_fallback": sig.is_fallback,
            "carbon_aggregation": sig.aggregation,
            "carbon_signal": sig.basis(),
            "water_stress_baseline": value,
            "water_stress_baseline_meta": meta,
        }
    return _label_cache


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
    """A new socket would exceed the per-user or global cap (``scope`` is ``"user"`` or ``"global"``)."""

    def __init__(self, scope: str) -> None:
        super().__init__(f"WebSocket connection limit reached ({scope})")
        self.scope = scope


# Close codes sent by the fan-out itself (the session-control codes live in api/routes/websocket_routes.py).
WS_CLOSE_SLOW_CLIENT = 1013  # try again later: send timed out, or too many consecutive dropped frames
WS_CLOSE_SEND_FAILED = 1011  # a send raised
_CLOSE_TIMEOUT_S = 1.0
_SERIAL = "serial"
_CONCURRENT = "concurrent"


@dataclass
class _Channel:
    """Per-client outbound state: a bounded queue (drop-oldest) drained by one writer task."""

    ws: object
    pending: deque = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    dropped_frames: int = 0
    consecutive_drops: int = 0


class ConnectionManager:
    """Tracks live WebSocket connections and fans one payload out to all of them.

    * T4a: optional per-user / global connection caps, checked atomically in ``connect``. The counts are
      kept in ``_owners`` / ``_per_user`` and released only by ``disconnect`` (what the route's ``finally``
      calls), so a socket that ``broadcast`` evicted still counts until its handler has actually ended.
    * T4b / T18: ``broadcast`` never awaits a client. Each client has a bounded queue (drop-oldest, so the
      newest state wins) and its own writer task; a send that does not finish within ``send_timeout`` closes
      the client with 1013, a send that raises closes it with 1011, and ``max_consecutive_drops`` dropped
      frames without one completed send closes it with 1013. One slow client therefore cannot delay others.
    * ``mode="serial"`` (BROADCAST_MODE=sequential) is the rollback: the old awaited, one-by-one send.
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
            self._mode = config._BROADCAST_MODES.get(str(mode).strip().lower(), _CONCURRENT)
        self._connections: set = set()
        self._channels: dict = {}
        self._owners: dict = {}  # ws -> user id (only sockets registered with a user)
        self._per_user: dict = {}  # user id -> number of registered sockets
        self._closers: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ registration
    def connect(
        self,
        websocket,
        user_id: str | None = None,
        *,
        max_per_user: int | None = None,
        max_global: int | None = None,
    ) -> None:
        """Register ``websocket``. With ``user_id`` and caps, raise ``ConnectionLimitExceeded`` BEFORE
        registering anything (check and registration happen with no await between them)."""
        if user_id is not None:
            if max_per_user is not None and self._per_user.get(user_id, 0) >= max_per_user:
                raise ConnectionLimitExceeded("user")
            if max_global is not None and len(self._owners) >= max_global:
                raise ConnectionLimitExceeded("global")
            if websocket not in self._owners:
                self._owners[websocket] = user_id
                self._per_user[user_id] = self._per_user.get(user_id, 0) + 1
        self._connections.add(websocket)
        self._channels.setdefault(websocket, _Channel(ws=websocket))
        WS_CONNECTIONS.set(len(self._connections))
        logger.info("WebSocket connected (%d active)", len(self._connections))

    def disconnect(self, websocket) -> None:
        """Release everything held for ``websocket``. Idempotent; a never-registered socket is a no-op."""
        self._connections.discard(websocket)
        self._drop_channel(websocket)
        user_id = self._owners.pop(websocket, None)
        if user_id is not None:
            left = self._per_user.get(user_id, 0) - 1
            if left > 0:
                self._per_user[user_id] = left
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
        if self._mode == _SERIAL:
            await self._broadcast_serial(payload)
            return
        for ws in list(self._connections):  # snapshot: connect/disconnect can run while we iterate
            channel = self._channels.get(ws)
            if channel is None:
                channel = self._channels[ws] = _Channel(ws=ws)
            if len(channel.pending) >= self._queue_depth:
                channel.pending.popleft()  # drop-oldest: the newest state wins
                channel.dropped_frames += 1
                channel.consecutive_drops += 1
                WS_DROPPED_MESSAGES.inc()
                if channel.consecutive_drops >= self._max_consecutive_drops:
                    self._evict(ws, WS_CLOSE_SLOW_CLIENT)
                    continue
            channel.pending.append(payload)
            channel.wake.set()
            if channel.task is None or channel.task.done():
                channel.task = asyncio.get_running_loop().create_task(self._writer(channel), name="ws-writer")

    async def _broadcast_serial(self, payload: dict) -> None:
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                self._evict(ws, WS_CLOSE_SEND_FAILED)

    async def _writer(self, channel: _Channel) -> None:
        ws = channel.ws
        while True:
            if not channel.pending:
                channel.wake.clear()
                await channel.wake.wait()
                continue
            frame = channel.pending.popleft()
            try:
                await asyncio.wait_for(ws.send_json(frame), self._send_timeout)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                self._evict(ws, WS_CLOSE_SLOW_CLIENT, from_writer=True)
                return
            except Exception:
                self._evict(ws, WS_CLOSE_SEND_FAILED, from_writer=True)
                return
            channel.consecutive_drops = 0

    # ------------------------------------------------------------------ eviction
    def _drop_channel(self, ws, *, keep_task: bool = False) -> None:
        channel = self._channels.pop(ws, None)
        if channel is not None and channel.task is not None and not keep_task and not channel.task.done():
            channel.task.cancel()

    def _evict(self, ws, code: int, *, from_writer: bool = False) -> None:
        """Remove ``ws`` from fan-out and close it. The user/global counts are NOT released here: the
        route's handler still owns the socket until it ends and calls ``disconnect``."""
        self._connections.discard(ws)
        self._drop_channel(ws, keep_task=from_writer)  # the writer that evicts is already returning
        WS_CONNECTIONS.set(len(self._connections))
        logger.warning("WebSocket evicted from live broadcast (close code %d)", code)
        close = getattr(ws, "close", None)
        if close is None:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._close(close, code))
        except RuntimeError:  # no running loop (synchronous caller): nothing to close with
            return
        self._closers.add(task)
        task.add_done_callback(self._closers.discard)

    @staticmethod
    async def _close(close, code: int) -> None:
        try:
            await asyncio.wait_for(close(code=code), _CLOSE_TIMEOUT_S)
        except Exception:  # already closed, or the peer is gone
            pass


manager = ConnectionManager()


async def _tick() -> dict:
    """One shared simulation step, used by every connected client."""
    global _water_stress_state, _tick_seq
    twin = get_twin()
    # T12: ONE clock read per tick; the diurnal hour is the SITE-local hour of that instant
    # (SITE_TIMEZONE), and ts_ingest below is that same instant in aware UTC.
    tick_now = utc_now()
    site_now = to_site_local(tick_now)
    hour = site_now.hour + site_now.minute / 60
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
    # T20: simulated seconds per tick come from SIM_STEP_SECONDS (default 300, A-1). Only physics v1
    # integrates a real step; legacy-0 is frozen at 300 s and keeps its default step.
    step_s = float(config.sim_step_seconds())
    if twin.physics_version == PHYSICS_V1:
        state = twin.step(action, dt_seconds=step_s)
    else:
        step_s = float(INTERVAL_MINUTES * 60)
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
        "ts_ingest": tick_now,
        "sim_time": state_dict["timestamp"],
        "sim_time_scale": step_s / BROADCAST_INTERVAL_SECONDS,
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
    labels = _labels()
    water_labels = {
        # ``water_stress`` (legacy key, unchanged value) IS the scenario: the loop's synthetic random walk.
        "water_stress_scenario": state_dict.get("water_stress", water_stress),
        "water_stress_kind": WATER_STRESS_KIND_SCENARIO,
        "water_stress_baseline": labels["water_stress_baseline"],
        "water_stress_baseline_meta": labels["water_stress_baseline_meta"],
    }
    return to_jsonable(
        {
            **state_dict,
            "carbon_data_is_real": twin.carbon_data_is_real,
            "carbon_semantic": labels["carbon_semantic"],
            "carbon_is_fallback": labels["carbon_is_fallback"],
            "carbon_aggregation": labels["carbon_aggregation"],
            **water_labels,
            **provenance,
            "anomaly_status": anomaly_status,
        }
    )


async def broadcast_once() -> None:
    """ONE iteration of the live loop, run by the supervisor (api/supervisor.py).

    No clients -> no tick and no database write, but the iteration still returns normally, so the supervisor
    keeps refreshing the heartbeat that /readyz reports. A failing tick raises: the supervisor restarts it.
    """
    if manager.has_connections():
        payload = await _tick()
        await manager.broadcast(payload)


async def run_broadcast_loop() -> None:
    """Unsupervised loop (kept for tests and rollback); production runs ``broadcast_once`` under the
    supervisor, started once in api/main.py's lifespan."""
    logger.info("Starting live broadcast loop (interval=%ds)", BROADCAST_INTERVAL_SECONDS)
    while True:
        try:
            await broadcast_once()
        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled")
            raise
        except Exception:
            logger.exception("Error in broadcast tick -- continuing")
        await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
