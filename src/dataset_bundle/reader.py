"""Read-only access to the dataset bundle (stdlib ``sqlite3`` only; opened ``mode=ro`` with ``query_only``).

This is the runtime side: it imports nothing from ``research`` and nothing heavy. Absence of the file is a distinct error
(``BundleNotFound``) so a route can answer 404, identical to an unknown route. Values are returned as exact decimal text
derived from the integer ticks; no float is ever formed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .errors import BundleError, BundleNotFound
from .schema import BUNDLE_FORMAT, QUALITY_NAMES, SCHEMA_VERSION, STATE_NAMES


def open_readonly(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise BundleNotFound("no dataset bundle at the configured path")
    conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        row = conn.execute("SELECT bundle_format, schema_version FROM dataset_version WHERE id = 1").fetchone()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise BundleError(f"not a dataset bundle: {exc}") from None
    if row is None or row["bundle_format"] != BUNDLE_FORMAT or row["schema_version"] != SCHEMA_VERSION:
        conn.close()
        raise BundleError("unsupported dataset bundle format or schema version")
    return conn


def format_ticks(ticks: int | None, decimals: int) -> str | None:
    """Exact decimal text of an integer number of resolution steps, e.g. (2130, 2) -> '21.30'."""
    if ticks is None:
        return None
    sign = "-" if ticks < 0 else ""
    digits = str(abs(ticks)).rjust(decimals + 1, "0")
    return f"{sign}{digits[:-decimals]}.{digits[-decimals:]}" if decimals else f"{sign}{digits}"


def dataset_version(conn: sqlite3.Connection) -> dict[str, Any]:
    d = dict(conn.execute("SELECT * FROM dataset_version WHERE id = 1").fetchone())
    d["counts"] = json.loads(d.pop("counts_json"))
    return d


def entities(conn: sqlite3.Connection, *, kind: str | None = None, tier: str | None = None) -> list[dict[str, Any]]:
    q, a = "SELECT * FROM entity WHERE 1=1", []
    if kind:
        q, a = q + " AND kind = ?", [*a, kind]
    if tier:
        q, a = q + " AND tier = ?", [*a, tier]
    out = []
    for r in conn.execute(q + " ORDER BY entity_pk", a):
        d = dict(r)
        for k in ("member_source_rack_ids", "evidence_refs"):
            d[k] = json.loads(d[k]) if d[k] is not None else None
        out.append(d)
    return out


def _entity(conn: sqlite3.Connection, external_id: str) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM entity WHERE external_id = ? AND kind = 'channel'", (external_id,)).fetchone()
    if r is None:
        raise BundleError(f"unknown channel {external_id!r}")
    if r["tier"] != "tier1" or not r["load_in_v1"]:
        raise BundleError(f"channel {external_id!r} is registered but not loaded")
    return r


def history(
    conn: sqlite3.Connection,
    sensor_external_id: str,
    *,
    from_t: int | None = None,
    to_t: int | None = None,
    after_t: int | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Stored records of one measured channel, ascending, half-open ``[from_t, to_t)``; keyset paging by ``after_t``.

    Seconds with no row are simply absent (never filled). ``limit`` is capped at 1000 (contract).
    """
    e = _entity(conn, sensor_external_id)
    lim = max(1, min(int(limit), 1000))
    q = (
        "SELECT o.t_naive_s, s.ts_text, o.value_ticks, o.state, o.quality, r.code AS reason_code, "
        "d.name AS disposition, s.group_size, s.first_row_ordinal "
        "FROM observation o JOIN second s ON s.t_naive_s = o.t_naive_s "
        "JOIN disposition d ON d.disposition_id = s.disposition_id "
        "LEFT JOIN reason_code r ON r.reason_id = o.reason_id WHERE o.entity_pk = ?"
    )
    a: list[Any] = [e["entity_pk"]]
    if from_t is not None:
        q, a = q + " AND o.t_naive_s >= ?", [*a, from_t]
    if after_t is not None:
        q, a = q + " AND o.t_naive_s > ?", [*a, after_t]
    if to_t is not None:
        q, a = q + " AND o.t_naive_s < ?", [*a, to_t]
    q += " ORDER BY o.t_naive_s LIMIT ?"
    return [
        {
            "sensor_external_id": sensor_external_id,
            "provenance": "measured",
            "t_naive_s": r["t_naive_s"],
            "ts_source_text": r["ts_text"],
            "value": format_ticks(r["value_ticks"], e["resolution_decimals"]),
            "value_ticks": r["value_ticks"],
            "unit": e["unit"],
            "state": STATE_NAMES[r["state"]],
            "quality": QUALITY_NAMES.get(r["quality"]),
            "reason_code": r["reason_code"],
            "disposition": r["disposition"],
            "group_size": r["group_size"],
            "row_ordinal": r["first_row_ordinal"],
        }
        for r in conn.execute(q, [*a, lim])
    ]


def derived_history(
    conn: sqlite3.Connection,
    derived_name: str,
    *,
    from_t: int | None = None,
    to_t: int | None = None,
    after_t: int | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Records of one derived series. Served only through this function, never through ``history``."""
    s = conn.execute("SELECT * FROM derived_series WHERE derived_name = ?", (derived_name,)).fetchone()
    if s is None:
        raise BundleError(f"unknown derived series {derived_name!r}")
    lim = max(1, min(int(limit), 1000))
    q = (
        "SELECT o.t_naive_s, sec.ts_text, o.value_ticks, o.state, o.quality, r.code AS reason_code "
        "FROM derived_observation o JOIN second sec ON sec.t_naive_s = o.t_naive_s "
        "LEFT JOIN reason_code r ON r.reason_id = o.reason_id WHERE o.series_pk = ?"
    )
    a: list[Any] = [s["series_pk"]]
    if from_t is not None:
        q, a = q + " AND o.t_naive_s >= ?", [*a, from_t]
    if after_t is not None:
        q, a = q + " AND o.t_naive_s > ?", [*a, after_t]
    if to_t is not None:
        q, a = q + " AND o.t_naive_s < ?", [*a, to_t]
    q += " ORDER BY o.t_naive_s LIMIT ?"
    return [
        {
            "derived_name": derived_name,
            "provenance": "derived",
            "t_naive_s": r["t_naive_s"],
            "ts_source_text": r["ts_text"],
            "value": format_ticks(r["value_ticks"], s["resolution_decimals"]),
            "value_ticks": r["value_ticks"],
            "unit": s["output_unit"],
            "state": STATE_NAMES[r["state"]],
            "quality": QUALITY_NAMES.get(r["quality"]),
            "reason_code": r["reason_code"],
            "output_scope": s["output_scope"],
            "output_member_source_rack_ids": json.loads(s["output_member_source_rack_ids"]),
        }
        for r in conn.execute(q, [*a, lim])
    ]
