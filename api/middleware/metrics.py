"""Prometheus metrics for the API layer."""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

registry = CollectorRegistry()

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status"], registry=registry)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"], registry=registry
)
MODEL_INFERENCE_COUNT = Counter("model_inference_total", "Model inference calls", ["model"], registry=registry)
# T16: telemetry ingest outcomes (label values are the fixed set in src.telemetry.validation.OUTCOMES).
TELEMETRY_SAMPLES_TOTAL = Counter(
    "telemetry_samples_total", "Telemetry samples by ingest outcome", ["outcome"], registry=registry
)
TELEMETRY_BATCHES_TOTAL = Counter("telemetry_ingest_batches_total", "ingest_samples calls", registry=registry)
for _outcome in (
    "accepted", "invalid_future", "invalid_range", "duplicate", "conflict",
    "unknown_sensor", "invalid_time", "unit_mismatch", "invalid_value",
):  # fmt: skip
    TELEMETRY_SAMPLES_TOTAL.labels(outcome=_outcome)  # pre-create so /metrics shows zeros from the start


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
        return response


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
