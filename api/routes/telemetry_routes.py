"""Telemetry read API (T17, roadmap 9.4).

    GET /api/telemetry/sensors/{external_id}/samples?from&to&stream=live&quality=ok&limit&cursor
    GET /api/telemetry/sensors/{external_id}/gaps?from&to&stream=live

* ``from`` / ``to`` are required RFC 3339 instants WITH an offset; a value without one is a 422 (it is never
  guessed to be UTC). ``to`` must be after ``from`` and the span at most ``TELEMETRY_MAX_SPAN_H`` hours (168).
  The interval is half-open: ``from <= ts_event < to``.
* ``stream`` defaults to ``live``; the filter is an exact match, so ``stream=live`` can never return replayed,
  imported or backfilled samples. Those are read through the same API with ``stream=replay:<uuid>`` etc.
* ``quality`` is ``ok`` (default), ``invalid`` or ``any``.
* Samples are ordered and paged by the keyset ``(ts_event, id)``: ``next_cursor`` is opaque, and inserts made
  between two requests never duplicate or skip a row that was already past the cursor.
* Timestamps are returned as UTC with a ``Z`` suffix. Each item carries ``origin``, ``stream_id`` and ``quality``.
* A GAP is a difference between two consecutive VALID (``quality=ok``) samples greater than
  ``1.5 x sampling_interval_s``. It is computed at read time; neither "gap" nor "stale" is ever stored.
* Viewer role (any authenticated user); rate class ``telemetry_read``.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import config
from api.auth import get_current_user
from api.rate_limit import http_limit
from api.services.telemetry_window import GAP_FACTOR
from database import get_db
from models.db_models import Sensor, TelemetrySample, User
from src.telemetry.validation import validate_stream_id

router = APIRouter(tags=["telemetry"], dependencies=[Depends(http_limit("telemetry_read"))])

MAX_LIMIT = 5000
DEFAULT_LIMIT = 1000
MAX_GAPS = 1000
_GAP_PAGE = 5000


# --------------------------------------------------------------------------- schemas


class SampleOut(BaseModel):
    ts_event: str
    ts_ingest: str
    value: float
    origin: str
    stream_id: str
    quality: str
    invalid_reason: Optional[str] = None


class SamplesResponse(BaseModel):
    external_id: str
    unit: str
    sampling_interval_s: float
    stream: str
    quality: str
    items: list[SampleOut]
    next_cursor: Optional[str] = None


class GapOut(BaseModel):
    start: str  # ts_event of the last valid sample before the gap
    end: str  # ts_event of the first valid sample after it
    duration_s: float


class GapsResponse(BaseModel):
    external_id: str
    stream: str
    sampling_interval_s: float
    threshold_s: float
    gaps: list[GapOut]
    truncated: bool = False


# --------------------------------------------------------------------------- helpers


def _utc(value: datetime) -> datetime:
    """Stored instants are UTC; SQLite hands them back naive."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _z(value: datetime) -> str:
    return _utc(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def parse_instant(name: str, raw: str) -> datetime:
    """RFC 3339 with an explicit offset (``Z`` or ``+hh:mm``). Naive -> 422."""
    text = raw.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text[-1:] in ("z", "Z") else text)
    except ValueError:
        raise _bad(f"'{name}' must be an RFC 3339 timestamp with a UTC offset, e.g. 2026-03-01T12:00:00Z") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _bad(f"'{name}' has no UTC offset; send e.g. 2026-03-01T12:00:00Z or 2026-03-01T12:00:00+05:30")
    return parsed.astimezone(timezone.utc)


def _range(frm: str, to: str) -> tuple[datetime, datetime]:
    start, end = parse_instant("from", frm), parse_instant("to", to)
    if end <= start:
        raise _bad("'to' must be after 'from'")
    max_h = config.telemetry_max_span_h()
    if end - start > timedelta(hours=max_h):
        raise _bad(f"'to' - 'from' must be at most {max_h} hours")
    return start, end


def _stream(stream: str) -> str:
    try:
        return validate_stream_id(stream)
    except ValueError as exc:
        raise _bad(str(exc)) from None


def encode_cursor(ts_event: datetime, row_id: int) -> str:
    raw = json.dumps({"t": _z(ts_event), "i": row_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        obj = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return parse_instant("cursor", obj["t"]), int(obj["i"])
    except (ValueError, KeyError, TypeError, binascii.Error, HTTPException):
        raise _bad("'cursor' is not valid; use the next_cursor of a previous response") from None


async def _sensor(session: AsyncSession, external_id: str) -> Sensor:
    sensor = (await session.execute(select(Sensor).where(Sensor.external_id == external_id))).scalar_one_or_none()
    if sensor is None:
        raise HTTPException(status_code=404, detail="Unknown sensor")
    return sensor


def _base_query(sensor: Sensor, stream: str, start: datetime, end: datetime):
    return select(TelemetrySample).where(
        TelemetrySample.sensor_id == sensor.id,
        TelemetrySample.stream_id == stream,
        TelemetrySample.ts_event >= start,
        TelemetrySample.ts_event < end,
    )


def _after(cursor: tuple[datetime, int]):
    ts, row_id = cursor
    return or_(TelemetrySample.ts_event > ts, and_(TelemetrySample.ts_event == ts, TelemetrySample.id > row_id))


# --------------------------------------------------------------------------- routes


@router.get("/api/telemetry/sensors/{external_id}/samples")
async def get_samples(
    external_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    frm: str = Query(..., alias="from", description="RFC 3339 instant with offset (inclusive)"),
    to: str = Query(..., description="RFC 3339 instant with offset (exclusive)"),
    stream: str = Query(default="live", max_length=64),
    quality: str = Query(default="ok", pattern="^(ok|invalid|any)$"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: Optional[str] = Query(default=None, max_length=256),
) -> SamplesResponse:
    start, end = _range(frm, to)
    stream = _stream(stream)
    after = decode_cursor(cursor) if cursor else None
    sensor = await _sensor(session, external_id)

    stmt = _base_query(sensor, stream, start, end)
    if quality != "any":
        stmt = stmt.where(TelemetrySample.quality == quality)
    if after is not None:
        stmt = stmt.where(_after(after))
    rows = (
        (await session.execute(stmt.order_by(TelemetrySample.ts_event, TelemetrySample.id).limit(limit + 1)))
        .scalars()
        .all()
    )
    page, more = rows[:limit], len(rows) > limit
    return SamplesResponse(
        external_id=sensor.external_id,
        unit=sensor.unit,
        sampling_interval_s=float(sensor.sampling_interval_s),
        stream=stream,
        quality=quality,
        items=[
            SampleOut(
                ts_event=_z(r.ts_event),
                ts_ingest=_z(r.ts_ingest),
                value=r.value,
                origin=r.origin,
                stream_id=r.stream_id,
                quality=r.quality,
                invalid_reason=r.invalid_reason,
            )
            for r in page
        ],
        next_cursor=encode_cursor(page[-1].ts_event, page[-1].id) if more and page else None,
    )


async def find_gaps(
    session: AsyncSession, sensor: Sensor, stream: str, start: datetime, end: datetime
) -> tuple[list[tuple[datetime, datetime]], bool]:
    """Gaps between consecutive valid samples in ``[start, end)``; at most MAX_GAPS (second item: truncated)."""
    threshold = timedelta(seconds=GAP_FACTOR * float(sensor.sampling_interval_s))
    gaps: list[tuple[datetime, datetime]] = []
    previous: Optional[datetime] = None
    after: Optional[tuple[datetime, int]] = None
    while True:
        stmt = _base_query(sensor, stream, start, end).where(TelemetrySample.quality == "ok")
        if after is not None:
            stmt = stmt.where(_after(after))
        rows = (
            (await session.execute(stmt.order_by(TelemetrySample.ts_event, TelemetrySample.id).limit(_GAP_PAGE)))
            .scalars()
            .all()
        )
        for r in rows:
            ts = _utc(r.ts_event)
            if previous is not None and ts - previous > threshold:
                if len(gaps) >= MAX_GAPS:
                    return gaps, True
                gaps.append((previous, ts))
            previous = ts
        if len(rows) < _GAP_PAGE:
            return gaps, False
        after = (rows[-1].ts_event, rows[-1].id)


@router.get("/api/telemetry/sensors/{external_id}/gaps")
async def get_gaps(
    external_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    frm: str = Query(..., alias="from", description="RFC 3339 instant with offset (inclusive)"),
    to: str = Query(..., description="RFC 3339 instant with offset (exclusive)"),
    stream: str = Query(default="live", max_length=64),
) -> GapsResponse:
    start, end = _range(frm, to)
    stream = _stream(stream)
    sensor = await _sensor(session, external_id)
    found, truncated = await find_gaps(session, sensor, stream, start, end)
    interval = float(sensor.sampling_interval_s)
    items: list[Any] = [GapOut(start=_z(a), end=_z(b), duration_s=(b - a).total_seconds()) for a, b in found]
    return GapsResponse(
        external_id=sensor.external_id,
        stream=stream,
        sampling_interval_s=interval,
        threshold_s=GAP_FACTOR * interval,
        gaps=items,
        truncated=truncated,
    )
