from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone

import numpy as np
from fastapi import WebSocket

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
    """A WebSocket connection cap was hit. ``scope`` is ``"user"`` or ``"global"``."""

    def __init__(self, scope: str) -> None:
        if scope not in ("user", "global"):
            raise ValueError(f"invalid connection-limit scope {scope!r}")
        super().__init__(f"{scope} connection limit reached")
        self.scope = scope


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts to all of them."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        # Cap bookkeeping (T4a). ``_owners`` maps each registered socket to its user;
        # ``_per_user`` counts them. Deliberately separate from ``_connections``:
        # broadcast() drops a socket whose send failed from ``_connections`` only, and
        # that socket keeps counting against the caps until disconnect() runs.
        self._owners: dict[WebSocket, str] = {}
        self._per_user: dict[str, int] = {}

    def connect(
        self,
        websocket: WebSocket,
        user_id: str | None = None,
        *,
        max_per_user: int | None = None,
        max_global: int | None = None,
    ) -> None:
        """Register ``websocket``. With a ``user_id`` and caps, raise
        ``ConnectionLimitExceeded`` (and register nothing) if a cap would be exceeded.
        There is no ``await`` here, so check-and-register is atomic on the event loop.
        Called without ``user_id``/caps it behaves as it did before T4a."""
        if user_id is not None:
            if websocket in self._owners:
                return
            if max_per_user is not None and self._per_user.get(user_id, 0) >= max_per_user:
                raise ConnectionLimitExceeded("user")
            if max_global is not None and len(self._owners) >= max_global:
                raise ConnectionLimitExceeded("global")
            self._owners[websocket] = user_id
            self._per_user[user_id] = self._per_user.get(user_id, 0) + 1
        self._connections.add(websocket)
        logger.info("WebSocket connected (%d active)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Idempotent; a socket that was never registered is a no-op."""
        self._connections.discard(websocket)
        user_id = self._owners.pop(websocket, None)
        if user_id is not None:
            remaining = self._per_user.get(user_id, 0) - 1
            if remaining > 0:
                self._per_user[user_id] = remaining
            else:
                self._per_user.pop(user_id, None)
        logger.info("WebSocket disconnected (%d active)", len(self._connections))

    def has_connections(self) -> bool:
        return bool(self._connections)

    async def broadcast(self, payload: dict) -> None:
        if not self._connections:
            return
        dead: list[WebSocket] = []
        # Iterate a snapshot: connect()/disconnect() can run while we await a
        # send, and mutating a set during iteration raises RuntimeError.
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)


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
