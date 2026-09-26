from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime

import numpy as np
from fastapi import WebSocket

from api.serialization import to_jsonable
from api.services.twin_service import get_twin
from database import get_session
from models.db_models import SensorReading

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


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts to all of them."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def connect(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)
        logger.info("WebSocket connected (%d active)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
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
    global _water_stress_state
    twin = get_twin()
    hour = datetime.now().hour + datetime.now().minute / 60
    utilisation = float(np.clip(0.4 + 0.5 * np.sin((hour - 6) * np.pi / 12), 0, 1))
    outside_temp = 22 + 5 * np.sin(2 * np.pi * (hour - 14) / 24) + random.uniform(-1, 1)
    _water_stress_state = float(np.clip(_water_stress_state + random.uniform(-_WATER_STRESS_STEP, _WATER_STRESS_STEP), 0, 0.5))
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
            session.add(SensorReading.from_state_dict(state_dict, "ws"))
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