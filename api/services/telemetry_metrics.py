"""Telemetry store counters (IG-04), registered on the API's existing Prometheus registry.

Names are fixed by the IG shared contract: ``telemetry_persist_failures_total`` (IG-10 alerts on it) and
``telemetry_retention_deleted_rows_total`` (IG-10 dashboard). Process-local, like every other series.
"""

from __future__ import annotations

from prometheus_client import Counter

from api.middleware.metrics import registry

TELEMETRY_PERSIST_FAILURES_TOTAL = Counter(
    "telemetry_persist_failures_total",
    "Live-tick persistence attempts that raised (store write, or the legacy fallback write)",
    registry=registry,
)
TELEMETRY_RETENTION_DELETED_ROWS_TOTAL = Counter(
    "telemetry_retention_deleted_rows_total",
    "telemetry_sample rows deleted by the retention job",
    registry=registry,
)
