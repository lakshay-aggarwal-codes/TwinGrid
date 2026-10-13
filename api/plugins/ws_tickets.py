"""Plugin: ``POST /auth/ws-ticket`` -- exchange a valid access token for a single-use WebSocket ticket (Task 6).

The access token travels in the ``Authorization`` header (never a URL). The ticket is then passed as
``/ws/live?ticket=<ticket>`` (see api/routes/websocket_routes.py). Store, TTL and rules: src/ws_tickets.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from api import auth
from api.errors import ApiError
from api.rate_limit import limiter
from models.db_models import User
from src import ws_tickets

router = APIRouter(prefix="/auth", tags=["auth"])


class WsTicketResponse(BaseModel):
    ticket: str
    expires_in: int


@router.post("/ws-ticket", response_model=WsTicketResponse)
@limiter.limit("30/minute")
async def create_ws_ticket(
    request: Request,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(auth.security)],
    user: Annotated[User, Depends(auth.get_current_user)],
) -> WsTicketResponse:
    """Single-use, opaque, short-lived (``WS_TICKET_TTL_SECONDS``, default 30). 503 if no ticket store is usable;
    the frontend then falls back to the token flow."""
    payload = auth.decode_token(credentials.credentials)
    try:
        ticket, ttl = await asyncio.to_thread(ws_tickets.issue_ticket, str(user.id), float(payload["exp"]))
    except ws_tickets.TicketStoreUnavailable:
        raise ApiError(503, "ws_ticket_unavailable", "WebSocket tickets are temporarily unavailable.") from None
    response.headers["Cache-Control"] = "no-store"
    return WsTicketResponse(ticket=ticket, expires_in=ttl)
