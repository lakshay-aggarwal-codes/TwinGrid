"""Dispatch alert events to registered webhook subscribers, so consumers
don't have to poll GET /api/alerts. Best-effort: a failed/slow subscriber
is logged and skipped, never allowed to block or fail the request that
triggered it (the anomaly-score call that generated the alert).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import requests

from api.services.webhook_security import WebhookURLError, validate_webhook_url
from src.webhook_registry import list_subscribers

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5


def webhook_on_simulated() -> bool:
    """WEBHOOK_ON_SIMULATED=true opts in to webhooks for alerts whose origin is "simulated".
    Default false (T3): nothing the simulator produces is a real incident."""
    return os.getenv("WEBHOOK_ON_SIMULATED", "false").strip().lower() in ("1", "true", "yes")


def webhook_allowed_for_origin(origin: str | None) -> bool:
    """Webhooks fire only for non-simulated origin unless WEBHOOK_ON_SIMULATED=true."""
    return origin != "simulated" or webhook_on_simulated()


def _post_one(url: str, payload: dict[str, Any]) -> None:
    try:
        # Re-validate at send time: DNS can change after registration.
        validate_webhook_url(url)
        # Redirects are refused so a public URL can't bounce us to an internal one.
        resp = requests.post(url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS, allow_redirects=False)
        if resp.status_code >= 400:
            logger.warning("Webhook %s returned %d", url, resp.status_code)
    except WebhookURLError as e:
        logger.warning("Webhook %s blocked: %s", url, e)
    except requests.RequestException as e:
        logger.warning("Webhook %s failed: %s", url, e)


async def dispatch_alert(alert: dict[str, Any]) -> None:
    """Fire-and-forget to every registered subscriber, in worker threads
    (requests is sync; this is called from an async route). Never raises --
    a webhook failure must not affect the alert that triggered it."""
    if not webhook_allowed_for_origin(alert.get("origin")):
        logger.info("Webhook suppressed: alert origin %r (set WEBHOOK_ON_SIMULATED=true to allow)", alert.get("origin"))
        return
    urls = list_subscribers()
    if not urls:
        return
    payload = {"event": "alert", **alert}
    await asyncio.gather(*(asyncio.to_thread(_post_one, url, payload) for url in urls), return_exceptions=True)
