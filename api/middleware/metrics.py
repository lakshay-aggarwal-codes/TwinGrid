"""Prometheus metrics for the API layer."""

from __future__ import annotations

import logging
import time

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

registry = CollectorRegistry()

access_logger = logging.getLogger("api.access")

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status"], registry=registry)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"], registry=registry
)
MODEL_INFERENCE_COUNT = Counter("model_inference_total", "Model inference calls", ["model"], registry=registry)

# T18 (section 8.5). Process-local, like every other series here.
BACKGROUND_LOOP_RESTARTS = Counter(
    "background_loop_restarts_total", "Supervisor restarts of a background loop", ["loop"], registry=registry
)
BACKGROUND_LOOP_LAST_SUCCESS = Gauge(
    "background_loop_last_success_timestamp",
    "Unix time of the last successful iteration of a background loop",
    ["loop"],
    registry=registry,
)
# T16: telemetry ingest. The sample counter is labelled by per-sample outcome (src/telemetry/validation.py OUTCOMES);
# the batch counter's name is the one tests/test_telemetry_ingest.py reads.
TELEMETRY_BATCHES_TOTAL = Counter(
    "telemetry_ingest_batches_total", "Telemetry ingest batches processed", registry=registry
)
TELEMETRY_SAMPLES_TOTAL = Counter(
    "telemetry_samples_total", "Telemetry samples by ingest outcome", ["outcome"], registry=registry
)
WS_CONNECTIONS = Gauge("ws_connections", "WebSocket clients currently registered for live broadcast", registry=registry)
WS_DROPPED_MESSAGES = Counter(
    "ws_dropped_messages_total",
    "Live frames discarded because a client's queue was full (drop-oldest)",
    registry=registry,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        # Use the matched route template (e.g. "/api/simulate/{hours}"),
        # not the raw URL -- otherwise every distinct `hours` value would
        # create its own Prometheus label series, which is a well-known
        # cardinality-blowup mistake.
        route = request.scope.get("route")
        path_template = route.path if route else request.url.path
        REQUEST_COUNT.labels(method=request.method, path=path_template, status=response.status_code).inc()
        REQUEST_LATENCY.labels(method=request.method, path=path_template).observe(duration)
        # T18: one structured access line per request (route/user_id were bound into the scope by
        # api.logging_config.bind_log_context; request_id comes from RequestIDMiddleware via the scope).
        access_logger.info(
            "%s %s -> %d",
            request.method,
            path_template,
            response.status_code,
            extra={
                "request_id": request.scope.get("request_id"),
                "route": path_template,
                "user_id": request.scope.get("log_user_id"),
                "status": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        return response


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
