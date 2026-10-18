"""Dispatch alert events to registered webhook subscribers, so consumers
don't have to poll GET /api/alerts. Best-effort: a failed/slow subscriber
is logged and skipped, never allowed to block or fail the request that
triggered it (the anomaly-score call that generated the alert).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

import requests

from api.services.webhook_security import WebhookURLError, validate_webhook_url
from src import webhook_deliveries
from src.admin_console.rules import webhook_id
from src.webhook_registry import list_subscribers

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5


def log_target(url: str) -> str:
    """What may appear in a log line for a subscriber: host and a short non-reversible id. The path and query of a
    webhook URL are often the secret itself (chat-tool incoming-webhook tokens), so they are never logged."""
    try:
        host = urlsplit(url).hostname or "invalid-url"
    except ValueError:
        host = "invalid-url"
    return f"{host} [{webhook_id(url)}]"


def webhook_on_simulated() -> bool:
    """WEBHOOK_ON_SIMULATED=true opts in to webhooks for alerts whose origin is "simulated".
    Default false (T3): nothing the simulator produces is a real incident."""
    return os.getenv("WEBHOOK_ON_SIMULATED", "false").strip().lower() in ("1", "true", "yes")


def webhook_allowed_for_origin(origin: str | None) -> bool:
    """Webhooks fire only for non-simulated origin unless WEBHOOK_ON_SIMULATED=true."""
    return origin != "simulated" or webhook_on_simulated()


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of one delivery attempt. ``ok`` = the subscriber answered 2xx; ``error_kind`` is a kind, never text."""

    ok: bool
    status_code: Optional[int]
    error_kind: Optional[str]
    duration_ms: int


def deliver(url: str, payload: dict[str, Any]) -> DeliveryResult:
    """POST ``payload`` to ``url`` once. Never raises. Redirects are refused (a public URL cannot bounce us to an internal
    one) and the URL is re-validated at send time (DNS can change after registration)."""
    start = time.monotonic()

    def done(ok: bool, status: Optional[int] = None, error: Optional[str] = None) -> DeliveryResult:
        return DeliveryResult(ok, status, error, int((time.monotonic() - start) * 1000))

    target = log_target(url)
    try:
        validate_webhook_url(url)
        resp = requests.post(url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS, allow_redirects=False)
        if resp.status_code >= 400:
            logger.warning("Webhook %s returned %d", target, resp.status_code)
            return done(False, resp.status_code, "http_error")
        if resp.status_code >= 300:
            return done(False, resp.status_code, "redirect_refused")
        return done(True, resp.status_code)
    except WebhookURLError as e:
        logger.warning("Webhook %s blocked: %s", target, e)
        return done(False, None, "blocked_url")
    # requests' exception text embeds the request path ("... Max retries exceeded with url: /secret"), so only the
    # exception class is logged.
    except requests.Timeout as e:
        logger.warning("Webhook %s failed: %s", target, type(e).__name__)
        return done(False, None, "timeout")
    except requests.ConnectionError as e:
        logger.warning("Webhook %s failed: %s", target, type(e).__name__)
        return done(False, None, "connection")
    except requests.RequestException as e:
        logger.warning("Webhook %s failed: %s", target, type(e).__name__)
        return done(False, None, "request_error")


def _record(kind: str, url: str, result: DeliveryResult) -> None:
    webhook_deliveries.record(
        webhook_deliveries.make_record(
            kind,
            url,
            ok=result.ok,
            status_code=result.status_code,
            error_kind=result.error_kind,
            duration_ms=result.duration_ms,
        )
    )


def _post_one(url: str, payload: dict[str, Any]) -> None:
    _record("alert", url, deliver(url, payload))


def build_test_payload() -> dict[str, Any]:
    """What an admin test-fire sends: clearly not an alert."""
    return {
        "event": "test",
        "origin": "admin_console",
        "note": "This is a test event from TwinGrid. It is not an alert.",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }


def send_test(url: str) -> DeliveryResult:
    """Deliver the test payload to one subscriber and record it in the delivery log (blocking: run in a thread)."""
    result = deliver(url, build_test_payload())
    _record("test", url, result)
    return result


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
