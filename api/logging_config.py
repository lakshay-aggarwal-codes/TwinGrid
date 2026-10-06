"""
Structured (JSON) logging for the API layer and, since T18, the ``src`` package.

Every line is one JSON object with ``timestamp, level, logger, message, request_id``, plus ``route`` and ``user_id``
when known, plus ``status`` and ``duration_ms`` on the per-request access line (logger ``api.access``).

* ``request_id`` comes from a ContextVar set by RequestIDMiddleware, so a line logged anywhere under a request
  (including ``src.*`` code called from a handler) carries the id of that request.
* ``route`` (the matched path template) and ``user_id`` (the ``sub`` of a SIGNATURE-VERIFIED bearer token; it is not a
  database lookup) are bound by the ``bind_log_context`` dependency, which api/main.py attaches to every router.
  The same two values are copied into the ASGI scope so the access-log line, written by an outer middleware that runs
  in a different task, can read them.

Deliberately separate from src/logging_config.py, which stays plain-text for the training/simulation progress output
when ``src`` is used standalone (notebooks, scripts); inside the API process the ``src`` logger is switched to JSON.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import Request

from api.middleware.request_id import request_id_var

route_var: ContextVar[str | None] = ContextVar("route", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

ACCESS_LOGGER = "api.access"
SCOPE_ROUTE_KEY = "log_route"
SCOPE_USER_KEY = "log_user_id"


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "route": getattr(record, "route", None) or route_var.get(),
            "user_id": getattr(record, "user_id", None) or user_id_var.get(),
        }
        for key in ("status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_api_logging(level: int = logging.INFO) -> None:
    """JSON handler on the ``api`` and ``src`` loggers (stdout). Idempotent."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    for name in ("api", "src"):
        target = logging.getLogger(name)
        target.handlers.clear()
        target.addHandler(handler)
        target.setLevel(level)
        target.propagate = False


async def bind_log_context(request: Request) -> None:
    """Router-level dependency: record the matched route and the verified user id for this request's log lines."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        route_var.set(path)
        request.scope[SCOPE_ROUTE_KEY] = path
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            from api.auth import decode_token  # lazy: api.auth needs JWT_SECRET_KEY at import

            sub = decode_token(token.strip()).get("sub")
        except Exception:
            sub = None
        if sub is not None:
            user_id_var.set(str(sub))
            request.scope[SCOPE_USER_KEY] = str(sub)
