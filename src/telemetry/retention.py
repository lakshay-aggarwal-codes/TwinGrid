"""Bounded retention for ``telemetry_sample`` (IG-04).

The live tick stores five rows per tick, so the table grows without limit unless old rows are removed.
``purge_expired`` deletes rows whose ``ts_event`` is older than ``TELEMETRY_RETENTION_DAYS`` in bounded batches,
one transaction per batch.

Scope: only ``stream_id = 'live'`` by default. ``replay:<uuid>`` and ``import:<dataset_id>`` streams are
deliberate datasets whose ``ts_event`` is old by design; an age cut-off would destroy them, so they are never
touched unless a caller names that stream explicitly. Rows are removed by primary key, so a concurrent
``ingest_samples`` can neither be blocked by nor lose a row to a purge of other rows.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import delete, func, select

from models.db_models import TelemetrySample
from src.timeutil import utc_now

logger = logging.getLogger(__name__)

RETENTION_DAYS_ENV = "TELEMETRY_RETENTION_DAYS"
RETENTION_INTERVAL_ENV = "TELEMETRY_RETENTION_INTERVAL_S"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_RETENTION_INTERVAL_S = 3600.0
DEFAULT_BATCH_SIZE = 5000
DEFAULT_MAX_BATCHES = 20  # per run: bounds how long one run holds the database
LIVE_STREAM = "live"


def _positive_number(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        value = 0.0
    if not value > 0 or value == float("inf"):
        logger.warning("%s=%r is not a positive number; using the default %s", name, raw, default)
        return default
    return value


def retention_days() -> int:
    """TELEMETRY_RETENTION_DAYS (default 30). Malformed or non-positive values fall back to the default."""
    return max(1, int(_positive_number(RETENTION_DAYS_ENV, DEFAULT_RETENTION_DAYS)))


def retention_interval_s() -> float:
    """TELEMETRY_RETENTION_INTERVAL_S (default 3600): minimum wall seconds between runs of the live loop."""
    return _positive_number(RETENTION_INTERVAL_ENV, DEFAULT_RETENTION_INTERVAL_S)


@dataclass(frozen=True)
class RetentionResult:
    cutoff: datetime
    stream_id: str
    deleted: int  # rows removed; with dry_run=True, rows that WOULD be removed
    batches: int
    more_remaining: bool  # True when the batch cap stopped the run before the table was clear
    dry_run: bool = False


def _record_deleted(n: int) -> None:
    """Best-effort Prometheus counter; metrics problems must never fail a purge."""
    if n <= 0:
        return
    try:
        from api.services.telemetry_metrics import TELEMETRY_RETENTION_DELETED_ROWS_TOTAL

        TELEMETRY_RETENTION_DELETED_ROWS_TOTAL.inc(n)
    except Exception:  # pragma: no cover
        logger.debug("retention metrics unavailable", exc_info=True)


async def purge_expired(
    session_factory: Callable[[], Any],
    *,
    now: datetime | None = None,
    days: int | None = None,
    stream_id: str = LIVE_STREAM,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_batches: int = DEFAULT_MAX_BATCHES,
    dry_run: bool = False,
) -> RetentionResult:
    """Delete (or with ``dry_run`` count) ``stream_id`` rows with ``ts_event`` older than ``days`` before ``now``.

    ``session_factory`` is called once per batch and must return an async context manager yielding a session
    (``database.get_session``). Each batch commits on its own, so a failure part-way keeps what was already deleted.
    A second run after a complete one deletes nothing.
    """
    if batch_size < 1 or max_batches < 1:
        raise ValueError("batch_size and max_batches must be >= 1")
    days = retention_days() if days is None else days
    if days < 1:
        raise ValueError("days must be >= 1")
    cutoff = (now if now is not None else utc_now()) - timedelta(days=days)
    expired = (TelemetrySample.stream_id == stream_id) & (TelemetrySample.ts_event < cutoff)

    if dry_run:
        async with session_factory() as session:
            n = (await session.execute(select(func.count()).select_from(TelemetrySample).where(expired))).scalar_one()
        return RetentionResult(cutoff, stream_id, int(n), 0, False, dry_run=True)

    deleted = 0
    batches = 0
    more = False
    while True:
        if batches >= max_batches:
            more = True
            break
        ids = select(TelemetrySample.id).where(expired).order_by(TelemetrySample.id).limit(batch_size)
        async with session_factory() as session:
            result = await session.execute(delete(TelemetrySample).where(TelemetrySample.id.in_(ids)))
            await session.commit()
        n = int(result.rowcount or 0)
        batches += 1
        deleted += n
        _record_deleted(n)
        if n < batch_size:
            break
    if deleted:
        logger.info(
            "Telemetry retention removed %d '%s' rows older than %s in %d batch(es)%s",
            deleted, stream_id, cutoff.isoformat(), batches, " (more remain)" if more else "",
        )  # fmt: skip
    return RetentionResult(cutoff, stream_id, deleted, batches, more)
