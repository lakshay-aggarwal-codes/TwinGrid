"""
Structured (JSON) logging for the API layer specifically.

Deliberately separate from src/logging_config.py, which stays plain-text
and continues to serve the ML/simulation modules' human-readable
training/simulation progress output -- that's a different audience with a
different need. Changing its format here would be an unrelated,
unrequested change to something that already works correctly.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from api.middleware.request_id import request_id_var


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_api_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    api_logger = logging.getLogger("api")
    api_logger.handlers.clear()
    api_logger.addHandler(handler)
    api_logger.setLevel(level)
    api_logger.propagate = False