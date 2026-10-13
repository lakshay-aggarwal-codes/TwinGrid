"""Plugin: ``POST /api/client-errors`` -- receive the browser's runtime error reports (Task 7).

What the reporter can send (src/lib/errorReporter.ts): a ``text/plain`` JSON body, by ``sendBeacon`` or ``fetch``, to
``VITE_ERROR_REPORT_URL``; it can attach NO header, so a bearer token is impossible. Authentication is therefore
token-bound: the URL carries a write-only report key, ``...?key=<CLIENT_ERRORS_REPORT_KEY>``. The key is visible in the
frontend bundle (a Sentry-DSN-like ingest key: it can only submit capped, redacted reports, never read anything).

Decision, in order (every refusal is counted in ``client_errors_received_total{outcome}`` and answered with the
standard problem body, never an internal detail):
  1. no usable key configured and ENVIRONMENT is production -> 404 ``disabled`` (the endpoint does not exist);
  2. more than ``CLIENT_ERRORS_RATE_LIMIT`` (20/minute) per client IP -> 429 ``rate_limited``;
  3. key configured and neither ``?key=`` nor a valid bearer access token matches -> 401 ``unauthorised``;
  4. body over ``CLIENT_ERRORS_MAX_BYTES`` (8192) -> 413 ``too_large`` (counted while reading, so it is never buffered);
  5. not a report -> 422 ``invalid``; otherwise 204 ``accepted`` and one redacted log line (logger ``api.client_errors``).
With no key in development/test the endpoint is open (rate-limited and capped), like ``/metrics`` there.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, Request, Response
from prometheus_client import Counter

from api import auth
from api.errors import ApiError
from api.middleware.metrics import registry
from api.rate_limit import _hit, client_ip, limiter, parse_rate
from src import client_errors as ce
from src.log_redaction import redact

logger = logging.getLogger("api.client_errors")
router = APIRouter(prefix="/api", tags=["observability"])

OUTCOMES = ("accepted", "disabled", "rate_limited", "unauthorised", "too_large", "invalid")
CLIENT_ERRORS_RECEIVED = Counter(
    "client_errors_received_total", "Browser error reports by outcome", ["outcome"], registry=registry
)
for _outcome in OUTCOMES:
    CLIENT_ERRORS_RECEIVED.labels(outcome=_outcome)  # series exist at 0 so rate() and alerts work from the start


def _refuse(outcome: str, status: int, detail: str, headers: dict[str, str] | None = None) -> ApiError:
    CLIENT_ERRORS_RECEIVED.labels(outcome=outcome).inc()
    return ApiError(status, outcome, detail, headers=headers)


def _bearer_ok(request: Request) -> bool:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return False
    try:
        return bool(auth.decode_token(token.strip()).get("sub"))
    except Exception:
        return False


async def _read_capped(request: Request, cap: int) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise _refuse("too_large", 413, f"Report too large (max {cap} bytes)")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > cap:
            raise _refuse("too_large", 413, f"Report too large (max {cap} bytes)")
    return bytes(body)


@router.post("/client-errors", status_code=204, response_class=Response)
async def receive_client_error(request: Request, key: str | None = Query(default=None, max_length=256)) -> Response:
    keyed = ce.configured_key() is not None
    if not keyed and ce.is_production():
        raise _refuse("disabled", 404, "Not found")
    if limiter.enabled:
        try:
            count, window = parse_rate(ce.rate_limit())
        except ValueError:
            count, window = parse_rate(ce.DEFAULT_RATE_LIMIT)
        retry_after = _hit("client_errors", f"ip:{client_ip(request)}", count, window)
        if retry_after is not None:
            raise _refuse("rate_limited", 429, "Too many reports", {"Retry-After": str(retry_after)})
    if keyed and not (ce.key_matches(key) or _bearer_ok(request)):
        raise _refuse("unauthorised", 401, "A report key or access token is required")
    raw = await _read_capped(request, ce.max_bytes())
    try:
        report = ce.parse_report(raw)
    except ce.InvalidReport as exc:
        raise _refuse("invalid", 422, str(exc)) from None
    CLIENT_ERRORS_RECEIVED.labels(outcome="accepted").inc()
    level = logging.ERROR if report["level"] == "error" else logging.WARNING
    logger.log(level, "client_error %s", redact(json.dumps(report, separators=(",", ":"))))
    return Response(status_code=204)


class RedactionFilter(logging.Filter):
    """Rewrites secrets (``?key=``, ``?token=``, bearer values ...) in a record's message and string arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


_SERVER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def setup(app: object) -> None:
    """The server's access log prints the full request target, so ``?key=`` must be redacted there too. Idempotent."""
    for name in _SERVER_LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactionFilter) for f in target.filters):
            target.addFilter(RedactionFilter())
