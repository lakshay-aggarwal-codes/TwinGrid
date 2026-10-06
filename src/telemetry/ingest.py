"""``ingest_samples``: the ONLY writer of ``telemetry_sample`` (roadmap §9.3, T16).

Rules implemented here (numbers refer to §9.3): unknown sensor (1), time (2), unit (3), finite value (4),
future/range stored-as-invalid (5), no imputation (6), ``INSERT .. ON CONFLICT DO NOTHING`` + duplicate/
conflict classification (7), out-of-order accepted (8), batch <= 1000 in one transaction with per-outcome
counts (9), idempotency via the unique key with replays/backfills on their own ``stream_id`` (10).

The caller owns the transaction: ``ingest_samples`` flushes but never commits, so the whole batch is atomic
with whatever else the caller does. A batch that raises leaves nothing behind once the caller rolls back.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import Sensor, TelemetrySample
from src.telemetry import validation as v
from src.timeutil import utc_now

logger = logging.getLogger(__name__)

MAX_BATCH = v.MAX_BATCH


class BatchTooLargeError(ValueError):
    """The batch has more than ``MAX_BATCH`` samples; nothing was processed."""


@dataclass(frozen=True)
class SampleResult:
    index: int
    external_id: Any
    outcome: str
    detail: str = ""


@dataclass
class IngestResult:
    batch_id: uuid.UUID
    ts_ingest: datetime
    counts: dict[str, int] = field(default_factory=dict)  # every outcome present, zeros included
    results: list[SampleResult] = field(default_factory=list)

    @property
    def stored(self) -> int:
        return (
            self.counts.get(v.ACCEPTED, 0) + self.counts.get(v.INVALID_FUTURE, 0) + self.counts.get(v.INVALID_RANGE, 0)
        )

    @property
    def rejected(self) -> int:
        return sum(self.counts.get(o, 0) for o in v.REJECTED)


def _insert_stmt(dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql.insert(TelemetrySample)
    if dialect_name == "sqlite":
        return sqlite.insert(TelemetrySample)
    raise NotImplementedError(f"ingest_samples supports PostgreSQL and SQLite, not {dialect_name!r}")


def _record_metrics(counts: Mapping[str, int]) -> None:
    """Best-effort Prometheus counters; telemetry must never fail because metrics are unavailable."""
    try:
        from api.middleware.metrics import TELEMETRY_BATCHES_TOTAL, TELEMETRY_SAMPLES_TOTAL

        TELEMETRY_BATCHES_TOTAL.inc()
        for outcome, n in counts.items():
            if n:
                TELEMETRY_SAMPLES_TOTAL.labels(outcome=outcome).inc(n)
    except Exception:  # pragma: no cover - import/registry problems must not break ingest
        logger.debug("telemetry metrics unavailable", exc_info=True)


async def ingest_samples(
    session: AsyncSession,
    samples: Sequence[Mapping[str, Any]],
    *,
    stream_id: str,
    origin: str,
    naive_policy: str = "reject",
    now: Optional[datetime] = None,
) -> IngestResult:
    """Validate and store a batch. Each sample is a mapping with ``external_id``, ``ts_event``, ``value`` and
    optionally ``unit``, ``source_tz`` (to read a naive ts_event) and ``sim_time`` (required iff
    ``origin='simulated'``).

    ``ts_ingest`` is one server clock read for the whole batch (``now`` is for tests only).
    Raises ``ValueError`` for batch-level misuse (bad stream_id/origin) and ``BatchTooLargeError`` for >1000.
    """
    stream_id = v.validate_stream_id(stream_id)
    origin = v.validate_origin(origin)
    if len(samples) > MAX_BATCH:
        raise BatchTooLargeError(f"batch of {len(samples)} exceeds the limit of {MAX_BATCH}")

    batch_id = uuid.uuid4()
    ts_ingest = now if now is not None else utc_now()
    counts: Counter[str] = Counter({o: 0 for o in v.OUTCOMES})
    results: list[SampleResult] = []

    ext_ids = {s.get("external_id") for s in samples if isinstance(s.get("external_id"), str)}
    sensors: dict[str, Sensor] = {}
    if ext_ids:
        rows = (await session.execute(select(Sensor).where(Sensor.external_id.in_(ext_ids)))).scalars().all()
        sensors = {r.external_id: r for r in rows}

    insert = _insert_stmt(session.get_bind().dialect.name)

    for i, s in enumerate(samples):
        ext = s.get("external_id")
        sensor = sensors.get(ext) if isinstance(ext, str) else None
        if sensor is None:  # rule 1
            counts[v.UNKNOWN_SENSOR] += 1
            results.append(SampleResult(i, ext, v.UNKNOWN_SENSOR, "no sensor with this external_id"))
            continue

        spec = v.SensorSpec(sensor.id, sensor.unit, sensor.source_tz, sensor.min_valid, sensor.max_valid)
        res = v.validate_sample(s, spec, origin=origin, ts_ingest=ts_ingest, naive_policy=naive_policy)
        if not res.storable:
            counts[res.outcome] += 1
            results.append(SampleResult(i, ext, res.outcome, res.detail))
            continue

        stmt = (
            insert.values(
                sensor_id=sensor.id,
                stream_id=stream_id,
                ts_event=res.ts_event,
                ts_ingest=ts_ingest,
                value=res.value,
                quality=res.quality,
                invalid_reason=res.invalid_reason,
                origin=origin,
                sim_time=res.sim_time,
                batch_id=batch_id,
            )
            .on_conflict_do_nothing(index_elements=["sensor_id", "stream_id", "ts_event"])
            .returning(TelemetrySample.id)
        )
        inserted = (await session.execute(stmt)).scalar_one_or_none()
        if inserted is not None:
            counts[res.outcome] += 1
            results.append(SampleResult(i, ext, res.outcome))
            continue

        # Rule 7: not inserted -> duplicate (same value) or conflict (different value; first write wins).
        existing = (
            await session.execute(
                select(TelemetrySample.value, TelemetrySample.batch_id).where(
                    TelemetrySample.sensor_id == sensor.id,
                    TelemetrySample.stream_id == stream_id,
                    TelemetrySample.ts_event == res.ts_event,
                )
            )
        ).one()
        if existing.value == res.value:
            counts[v.DUPLICATE] += 1
            results.append(SampleResult(i, ext, v.DUPLICATE))
        else:
            counts[v.CONFLICT] += 1
            detail = f"kept {existing.value!r}, rejected {res.value!r}"
            results.append(SampleResult(i, ext, v.CONFLICT, detail))
            logger.warning(
                "telemetry conflict sensor=%s stream=%s ts_event=%s kept=%r (batch %s) rejected=%r (batch %s)",
                ext,
                stream_id,
                res.ts_event.isoformat(),
                existing.value,
                existing.batch_id,
                res.value,
                batch_id,
            )

    await session.flush()
    out = IngestResult(batch_id=batch_id, ts_ingest=ts_ingest, counts=dict(counts), results=results)
    _record_metrics(out.counts)
    return out
