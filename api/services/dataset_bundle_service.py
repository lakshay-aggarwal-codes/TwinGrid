"""Task 16: read-only dataset telemetry service over the Task 15 bundle (``src/dataset_bundle``).

* Imports nothing from ``research``. The record and envelope shapes follow ``TASK_08_CONTRACT.md`` (contract 1.1.0);
  the reference validator is exercised by the tests, not imported here.
* Reads only through a ``mode=ro`` connection opened per request (``src.dataset_bundle.reader.open_readonly``).
  Measured series come from ``observation``; the one derived series comes from ``derived_observation``. The two are
  never mixed. Nothing is written, filled, interpolated, split per rack or converted to UTC.
* Time is the naive source label (``YYYY-MM-DD HH:MM:SS``); the source timezone is not established.
* Configuration (read from the environment on every call, so tests and operators can change it without a restart):
  ``DATASET_BUNDLE_PATH`` (file) and ``DATASET_FACILITY_ID`` (the facility id requests must send).
"""

from __future__ import annotations

import base64
import binascii
import calendar
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from src.dataset_bundle.reader import dataset_version, format_ticks, open_readonly
from src.dataset_bundle.schema import QUALITY_NAMES, STATE_NAMES

CONTRACT_VERSION = "1.1.0"
BUNDLE_ENV = "DATASET_BUNDLE_PATH"
FACILITY_ENV = "DATASET_FACILITY_ID"
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
ALL_STATES = ("observed", "missing", "invalid", "not_reported", "stale")
DEFAULT_STATES = ("observed", "missing")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
FLAGGED_REASON_NOT_STORED = (
    "flagged_reason_not_stored"  # the bundle keeps no reason for a flagged cell (none exist in v5)
)
STATE_CODE = {name: code for code, name in STATE_NAMES.items()}


class DatasetError(Exception):
    """A dataset-domain failure; the route renders it as the contract's error envelope."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ----------------------------------------------------------------------------------------------- configuration


def configured_path() -> Path | None:
    raw = os.getenv(BUNDLE_ENV, "").strip()
    return Path(raw) if raw else None


def configured_facility() -> str | None:
    raw = os.getenv(FACILITY_ENV, "").strip()
    return raw or None


def bundle_available() -> bool:
    """True only when both settings exist and the file is there. Otherwise the routes answer as if they did not exist."""
    p = configured_path()
    return bool(p and configured_facility() and p.is_file())


@contextmanager
def bundle() -> Iterator[sqlite3.Connection]:
    path = configured_path()
    if path is None:
        raise DatasetError(404, "unknown_dataset", "no dataset is configured")
    conn = open_readonly(path)
    try:
        yield conn
    finally:
        conn.close()


# ----------------------------------------------------------------------------------------------- request context


class Ctx:
    """Validated request identity plus the bundle's dataset record (one per request)."""

    def __init__(self, conn: sqlite3.Connection, facility_id: str, dataset_id: str, stream: str) -> None:
        self.conn = conn
        self.dv = dataset_version(conn)
        self.facility_id, self.dataset_id, self.stream = facility_id, dataset_id, stream
        self.file = self.dv["raw_file_name"]
        row = conn.execute("SELECT MIN(t_naive_s) a, MAX(t_naive_s) b FROM second").fetchone()
        self.first_t, self.last_t = row["a"], row["b"]

    def envelope(self, kind: str, **fields: Any) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "kind": kind,
            "facility_id": self.facility_id,
            "dataset_id": self.dataset_id,
            "stream_id": self.stream,
            **fields,
        }


def make_ctx(conn: sqlite3.Connection, facility_id: str | None, dataset_id: str, stream: str | None) -> Ctx:
    """Order: facility given, stream given, facility known, dataset known, stream is this dataset's import stream."""
    if not facility_id:
        raise DatasetError(400, "bad_request", "facility_id is required on every dataset request")
    if not stream:
        raise DatasetError(400, "stream_required", "stream is required (import:<dataset_id>); there is no default")
    if facility_id != configured_facility():
        raise DatasetError(404, "unknown_facility", "unknown facility_id")
    ctx = Ctx(conn, facility_id, dataset_id, stream)
    if dataset_id != ctx.dv["dataset_id"]:
        raise DatasetError(404, "unknown_dataset", "unknown dataset_id")
    if stream != ctx.dv["stream"]:
        raise DatasetError(400, "bad_request", f"stream must be {ctx.dv['stream']!r} for this dataset (never 'live')")
    return ctx


def error_envelope(err: DatasetError, facility_id: str | None, dataset_id: str | None, stream: str | None) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "error",
        "status": err.status,
        "code": err.code,
        "message": err.message,
        "facility_id": facility_id,
        "dataset_id": dataset_id,
        "stream_id": stream,
    }


# ----------------------------------------------------------------------------------------------- parameters


def parse_source_text(name: str, text: str | None) -> int | None:
    """Naive label-seconds (``calendar.timegm`` semantics: no zone, no DST), or None when the parameter is absent."""
    if text is None or text == "":
        return None
    if not TS_RE.match(text):
        raise DatasetError(
            400, "bad_request", f"'{name}' must be source text 'YYYY-MM-DD HH:MM:SS' (no zone or offset)"
        )
    try:
        return calendar.timegm(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timetuple())
    except ValueError:
        raise DatasetError(400, "bad_request", f"'{name}' is not a valid date and time") from None


def parse_bool(name: str, text: str | None, default: bool = False) -> bool:
    if text is None or text == "":
        return default
    if text.lower() in ("true", "1"):
        return True
    if text.lower() in ("false", "0"):
        return False
    raise DatasetError(400, "bad_request", f"'{name}' must be true or false")


def parse_limit(text: str | None) -> int:
    if text is None or text == "":
        return DEFAULT_LIMIT
    if not text.isdigit() or not 1 <= int(text) <= MAX_LIMIT:
        raise DatasetError(400, "bad_request", f"'limit' must be an integer from 1 to {MAX_LIMIT}")
    return int(text)


def parse_states(text: str | None) -> list[str]:
    if text is None or text == "":
        return list(DEFAULT_STATES)
    states = [s.strip() for s in text.split(",") if s.strip()]
    if not states or any(s not in ALL_STATES for s in states) or len(set(states)) != len(states):
        raise DatasetError(400, "bad_request", f"'include_states' is a comma list of {', '.join(ALL_STATES)}")
    return states


def encode_cursor(t: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"t": t}, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int | None:
    if not cursor:
        return None
    try:
        obj = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        t = obj["t"]
        if isinstance(t, bool) or not isinstance(t, int):
            raise ValueError
        return t
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise DatasetError(400, "bad_request", "'cursor' is not a cursor issued by this API") from None


# ----------------------------------------------------------------------------------------------- registry lookups


def _json_list(text: str | None) -> list:
    return json.loads(text) if text else []


def _channels(ctx: Ctx) -> list[sqlite3.Row]:
    return ctx.conn.execute(
        "SELECT * FROM entity WHERE kind = 'channel' AND tier = 'tier1' AND load_in_v1 = 1 ORDER BY entity_pk"
    ).fetchall()


def channel(ctx: Ctx, sensor: str) -> sqlite3.Row:
    r = ctx.conn.execute("SELECT * FROM entity WHERE kind = 'channel' AND external_id = ?", (sensor,)).fetchone()
    if r is None:
        raise DatasetError(404, "unknown_entity", "unknown sensor_external_id for this dataset")
    if r["tier"] != "tier1" or not r["load_in_v1"]:
        raise DatasetError(
            404, "unknown_entity", "this sensor is registered in the dataset but its values are not loaded in v1"
        )
    return r


def derived_series(ctx: Ctx, name: str) -> sqlite3.Row:
    r = ctx.conn.execute("SELECT * FROM derived_series WHERE derived_name = ?", (name,)).fetchone()
    if r is None:
        raise DatasetError(404, "unknown_entity", "unknown derived series for this dataset")
    return r


# ----------------------------------------------------------------------------------------------- records


def _attribution(scope: str, members: list[str]) -> dict[str, Any]:
    return {"scope": scope, "member_source_rack_ids": members, "split_allowed": False}


def _value_fields(value_ticks: int | None, decimals: int) -> tuple[float | None, str | None]:
    text = format_ticks(value_ticks, decimals)
    return (float(text) if text is not None else None), text


def _row_sql(table: str, key: str) -> str:
    """Measured and derived rows share a shape; the join differs only by table and key column."""
    return (
        f"SELECT o.t_naive_s, s.ts_text, o.value_ticks, o.state, o.quality, r.code AS reason_code, "
        f"d.name AS disposition, s.group_size, s.first_row_ordinal "
        f"FROM {table} o JOIN second s ON s.t_naive_s = o.t_naive_s "
        f"JOIN disposition d ON d.disposition_id = s.disposition_id "
        f"LEFT JOIN reason_code r ON r.reason_id = o.reason_id WHERE o.{key} = ?"
    )


def fetch_rows(
    ctx: Ctx,
    *,
    derived: bool,
    pk: int,
    exact: int | None = None,
    last: bool = False,
    from_t: int | None = None,
    to_t: int | None = None,
    after_t: int | None = None,
    states: list[str] | None = None,
    limit: int = 1,
) -> list[sqlite3.Row]:
    sql = _row_sql("derived_observation", "series_pk") if derived else _row_sql("observation", "entity_pk")
    args: list[Any] = [pk]
    if exact is not None:
        sql, args = sql + " AND o.t_naive_s = ?", [*args, exact]
    if from_t is not None:
        sql, args = sql + " AND o.t_naive_s >= ?", [*args, from_t]
    if after_t is not None:
        sql, args = sql + " AND o.t_naive_s > ?", [*args, after_t]
    if to_t is not None:
        sql, args = sql + " AND o.t_naive_s < ?", [*args, to_t]
    if states is not None:
        codes = [STATE_CODE[s] for s in states if s in STATE_CODE]
        if not codes:
            return []
        sql, args = sql + f" AND o.state IN ({','.join('?' * len(codes))})", [*args, *codes]
    sql += " ORDER BY o.t_naive_s " + ("DESC" if last else "ASC") + " LIMIT ?"
    return ctx.conn.execute(sql, [*args, limit]).fetchall()


def _state_fields(row: sqlite3.Row) -> tuple[str, bool, str | None, str | None]:
    state = STATE_NAMES[row["state"]]
    quality = QUALITY_NAMES.get(row["quality"])
    reason = row["reason_code"]
    if state == "observed" and quality == "flagged" and reason is None:
        reason = FLAGGED_REASON_NOT_STORED
    return state, state == "observed", quality, reason


def measured_record(ctx: Ctx, ent: sqlite3.Row, row: sqlite3.Row) -> dict[str, Any]:
    state, observed, quality, reason = _state_fields(row)
    value, text = _value_fields(row["value_ticks"], ent["resolution_decimals"])
    ts = row["ts_text"]
    flagged = quality == "flagged"
    disposition = "flagged" if flagged else row["disposition"]
    return {
        "contract_version": CONTRACT_VERSION,
        "record_kind": "telemetry_record",
        "facility_id": ctx.facility_id,
        "site_status": "location_not_established",
        "dataset_id": ctx.dataset_id,
        "stream_id": ctx.stream,
        "source_rack_id": ent["source_rack_id"],
        "source_server_id": None,
        "source_server_status": "not_present_in_source",
        "asset_external_id": ent["asset_external_id"],
        "sensor_external_id": ent["external_id"],
        "mapping": {
            "mapping_id": ent["mapping_id"],
            "mapping_version": ent["mapping_version"],
            "method": ent["method"],
            "label_evidence": ent["label_evidence"],
            "valid_time_status": ent["valid_time_status"],
            "applied_uniformly_over_window": True,
        },
        "time_basis": ctx.dv["time_basis"],
        "ts_source_text": ts,
        "ts_utc": None,
        "measurand": ent["measurand"],
        "unit": ent["unit"],
        "value": value,
        "value_text": text,
        "resolution_decimals": ent["resolution_decimals"],
        "state": state,
        "observed": observed,
        "quality": quality,
        "reason_code": reason,
        "age_seconds": None,
        "provenance": "measured",
        "storage_class": "research_import_file",
        "origin_db": None,
        "attribution": _attribution(ent["attribution_scope"], _json_list(ent["member_source_rack_ids"])),
        "source_ref": {
            "file": ctx.file,
            "column": ent["source_column"],
            "row_ordinal": row["first_row_ordinal"],
            "row_numbering": "data_row_ordinal_excluding_header",
            "ts_text": ts,
            "key": f"{ctx.file}|{ent['source_column']}|{ts}",
            "file_sha256": ctx.dv["raw_file_sha256"],
        },
        "ledger": {"row_disposition": disposition, "group_size": row["group_size"], "group_ref": f"{ctx.file}|{ts}"},
        "derivation": None,
        "protocol_ref": {"protocol_sha256": ctx.dv["protocol_sha256"]},
        "fixture": False,
    }


def _derived_asset(ctx: Ctx) -> str:
    r = ctx.conn.execute("SELECT asset_external_id FROM entity WHERE kind = 'zone' ORDER BY entity_pk").fetchone()
    if r is None:
        raise DatasetError(500, "internal", "the bundle has no zone entity to attach the derived total to")
    return r["asset_external_id"]


def derived_record(ctx: Ctx, series: sqlite3.Row, row: sqlite3.Row) -> dict[str, Any]:
    state, observed, quality, reason = _state_fields(row)
    value, text = _value_fields(row["value_ticks"], series["resolution_decimals"])
    ts = row["ts_text"]
    inputs = _json_list(series["inputs_json"])
    ents = [channel(ctx, i) for i in inputs]
    members = _json_list(series["output_member_source_rack_ids"])
    return {
        "contract_version": CONTRACT_VERSION,
        "record_kind": "telemetry_record",
        "facility_id": ctx.facility_id,
        "site_status": "location_not_established",
        "dataset_id": ctx.dataset_id,
        "stream_id": ctx.stream,
        "source_rack_id": None,
        "source_server_id": None,
        "source_server_status": "not_present_in_source",
        "asset_external_id": _derived_asset(ctx),
        "sensor_external_id": series["derived_name"],
        "mapping": None,
        "time_basis": ctx.dv["time_basis"],
        "ts_source_text": ts,
        "ts_utc": None,
        "measurand": series["output_measurand"],
        "unit": series["output_unit"],
        "value": value,
        "value_text": text,
        "resolution_decimals": series["resolution_decimals"],
        "state": state,
        "observed": observed,
        "quality": quality,
        "reason_code": reason,
        "age_seconds": None,
        "provenance": "derived",
        "storage_class": "derived_series",
        "origin_db": None,
        "attribution": _attribution(series["output_scope"], members),
        "source_ref": None,
        "ledger": None,
        "derivation": {
            "formula_id": series["formula_id"],
            "formula_text": series["formula_text"],
            "inputs": [
                {"sensor_external_id": e["external_id"], "source_ref_key": f"{ctx.file}|{e['source_column']}|{ts}"}
                for e in ents
            ],
            "input_scopes": [e["attribution_scope"] for e in ents],
            "mapping_id": ",".join(sorted({e["mapping_id"] for e in ents})),
            "mapping_version": int(ctx.dv["mapping_version"]),
            "code_version": f"mapping-v{ctx.dv['mapping_version']}",
            "method_approval_ref": series["method_approval_ref"],
        },
        "protocol_ref": {"protocol_sha256": ctx.dv["protocol_sha256"]},
        "fixture": False,
    }


def _record(ctx: Ctx, ent: sqlite3.Row, row: sqlite3.Row, derived: bool) -> dict[str, Any]:
    return derived_record(ctx, ent, row) if derived else measured_record(ctx, ent, row)


def _pk(ent: sqlite3.Row, derived: bool) -> int:
    return ent["series_pk"] if derived else ent["entity_pk"]


def _name(ent: sqlite3.Row, derived: bool) -> str:
    return ent["derived_name"] if derived else ent["external_id"]


# ----------------------------------------------------------------------------------------------- envelopes


def sensor_list(ctx: Ctx, measurand: str | None, source_rack_id: str | None) -> dict[str, Any]:
    """Measured channels loaded in v1. A group power channel has no source rack, so it never appears under a rack filter."""
    items = []
    for e in _channels(ctx):
        if measurand and e["measurand"] != measurand:
            continue
        if source_rack_id and e["source_rack_id"] != source_rack_id:
            continue
        items.append(
            {
                "sensor_external_id": e["external_id"],
                "asset_external_id": e["asset_external_id"],
                "measurand": e["measurand"],
                "unit": e["unit"],
                "mapping_id": e["mapping_id"],
                "mapping_version": e["mapping_version"],
                "method": e["method"],
                "measurand_status": "sensor_present",
            }
        )
    return ctx.envelope("sensor_list", count=len(items), items=items)


def latest(ctx: Ctx, name: str, as_of_text: str | None, *, derived: bool) -> dict[str, Any]:
    ent = derived_series(ctx, name) if derived else channel(ctx, name)
    as_of = parse_source_text("as_of_source_text", as_of_text)
    rec, reason, window = _latest_record(ctx, ent, as_of, derived)
    return ctx.envelope(
        "latest",
        sensor_external_id=_name(ent, derived),
        measurand_status="sensor_present",
        window_status=window,
        record_absent_reason=reason,
        record=rec,
    )


def _latest_record(ctx: Ctx, ent: sqlite3.Row, as_of: int | None, derived: bool):
    pk = _pk(ent, derived)
    if as_of is None:
        rows = fetch_rows(ctx, derived=derived, pk=pk, last=True)
        return (
            (_record(ctx, ent, rows[0], derived), None, "inside_dataset_window")
            if rows
            else (
                None,
                "not_reported_at_time",
                "inside_dataset_window",
            )
        )
    rows = fetch_rows(ctx, derived=derived, pk=pk, exact=as_of)
    inside = ctx.first_t is not None and ctx.first_t <= as_of <= ctx.last_t
    if rows:
        return _record(ctx, ent, rows[0], derived), None, "inside_dataset_window"
    return (
        None,
        ("not_reported_at_time" if inside else "outside_dataset_window"),
        ("inside_dataset_window" if inside else "outside_dataset_window"),
    )


def history(
    ctx: Ctx,
    name: str,
    *,
    derived: bool,
    from_text: str | None,
    to_text: str | None,
    include_states: str | None,
    include_invalid: str | None,
    limit: str | None,
    cursor: str | None,
) -> dict[str, Any]:
    ent = derived_series(ctx, name) if derived else channel(ctx, name)
    from_t, to_t = parse_source_text("from_source_text", from_text), parse_source_text("to_source_text", to_text)
    if from_t is not None and to_t is not None and to_t <= from_t:
        raise DatasetError(400, "bad_request", "'to_source_text' must be after 'from_source_text'")
    states, inv, lim, after = (
        parse_states(include_states),
        parse_bool("include_invalid", include_invalid),
        parse_limit(limit),
        decode_cursor(cursor),
    )
    rows = fetch_rows(
        ctx,
        derived=derived,
        pk=_pk(ent, derived),
        from_t=from_t,
        to_t=to_t,
        after_t=after,
        states=states,
        limit=lim + 1,
    )
    page = rows[:lim]
    nxt = encode_cursor(page[-1]["t_naive_s"]) if len(rows) > lim else None
    records = [_record(ctx, ent, r, derived) for r in page]
    return ctx.envelope(
        "history",
        sensor_external_id=_name(ent, derived),
        from_source_text=from_text or None,
        to_source_text=to_text or None,
        include_invalid=inv,
        include_states=states,
        count=len(records),
        page={"limit": lim, "next_cursor": nxt},
        records=records,
    )


def rack_view(ctx: Ctx, rack: str, as_of_text: str | None) -> dict[str, Any]:
    r = ctx.conn.execute("SELECT * FROM entity WHERE kind = 'rack' AND source_rack_id = ?", (rack,)).fetchone()
    if r is None:
        raise DatasetError(404, "unknown_entity", "unknown source_rack_id for this dataset")
    as_of = parse_source_text("as_of_source_text", as_of_text)
    temps, power_ent = [], []
    for e in _channels(ctx):
        if e["measurand"] == "temperature" and e["source_rack_id"] == rack:
            rec, _, _ = _latest_record(ctx, e, as_of, False)
            temps.append(
                {
                    "sensor_external_id": e["external_id"],
                    "source_label": e["source_label"],
                    "source_position_word": e["source_position_word"],
                    "label_evidence": e["label_evidence"],
                    "record": rec,
                }
            )
        elif e["measurand"] == "power" and rack in _json_list(e["member_source_rack_ids"]):
            power_ent.append(e)
    if not power_ent:
        power: dict[str, Any] = {"kind": "not_available", "reason": "no_power_channel_for_this_rack"}
    else:
        p = power_ent[0]
        members = _json_list(p["member_source_rack_ids"])
        if p["attribution_scope"] == "rack_group" and len(members) >= 2:
            power = {
                "kind": "group_pointer",
                "sensor_external_id": p["external_id"],
                "member_source_rack_ids": members,
                "value": None,
                "split_allowed": False,
            }
        else:
            rec, _, _ = _latest_record(ctx, p, as_of, False)
            power = (
                {"kind": "single_rack_port", "record": rec}
                if rec
                else {
                    "kind": "not_available",
                    "reason": "no_record_at_that_second",
                }
            )
    return ctx.envelope(
        "rack_view",
        source_rack_id=rack,
        asset_external_id=r["asset_external_id"],
        temperature_sensors=temps,
        power=power,
    )


def dataset_record(ctx: Ctx) -> dict[str, Any]:
    dv = ctx.dv
    racks = [
        {"source_rack_id": e["source_rack_id"], "asset_external_id": e["asset_external_id"], "name": e["name"]}
        for e in ctx.conn.execute("SELECT * FROM entity WHERE kind = 'rack' ORDER BY entity_pk")
    ]
    series = []
    for s in ctx.conn.execute("SELECT * FROM derived_series ORDER BY series_pk"):
        series.append(
            {
                "derived_name": s["derived_name"],
                "provenance": "derived",
                "formula_id": s["formula_id"],
                "formula_text": s["formula_text"],
                "inputs": _json_list(s["inputs_json"]),
                "measurand": s["output_measurand"],
                "unit": s["output_unit"],
                "output_scope": s["output_scope"],
                "output_member_source_rack_ids": _json_list(s["output_member_source_rack_ids"]),
                "split_per_rack": False,
                "method_approval_ref": s["method_approval_ref"],
                "code_version": f"mapping-v{dv['mapping_version']}",
                "code_version_note": "derived from the bundle's mapping version; the bundle stores no code version",
                "asset_external_id": _derived_asset(ctx),
            }
        )
    return ctx.envelope(
        "dataset_record",
        version=dv["version"],
        doi=dv["doi"],
        source_url=dv["source_url"],
        licence=dv["licence_name"],
        attribution_text=dv["attribution_text"],
        modifications_statement=dv["modifications_statement"],
        access_status=dv["access_status"],
        data_status="historical_import_not_live",
        time_basis=dv["time_basis"],
        time_note="Source labels carry no declared timezone; no UTC value is provided.",
        window={"first_source_text": dv["window_first_text"], "last_source_text": dv["window_last_text"]},
        racks=racks,
        measured_series_count=len(_channels(ctx)),
        derived_series=series,
        mapping_version=dv["mapping_version"],
        protocol_sha256=dv["protocol_sha256"],
        panel_sha256=dv["panel_sha256"],
        content_digest=dv["content_digest"],
        derived_content_digest=dv["derived_content_digest"],
    )
