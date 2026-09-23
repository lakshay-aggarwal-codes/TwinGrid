from __future__ import annotations

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.auth import decode_token
from api.services.live_broadcast_service import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["live"])


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket, token: str = Query(..., alias="token")):
    """Live state updates, broadcast from ONE shared simulation loop (see
    api/services/live_broadcast_service.py) to every connected client --
    not one independent loop per connection. Requires JWT:
    /ws/live?token=<access_token>.
    """
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    manager.connect(websocket)
    try:
        while True:
            # This connection only ever receives broadcasts; it never sends
            # anything meaningful itself. receive() blocks until either a
            # (discarded) client message arrives or the socket closes --
            # the standard FastAPI pattern for detecting disconnect on a
            # server-push-only connection.
            await websocket.receive()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
    finally:
        manager.disconnect(websocket)