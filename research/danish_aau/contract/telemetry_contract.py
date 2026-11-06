"""TwinGrid canonical telemetry and provenance contract, version 1.0.0 (Task 8).

Pure, stdlib-only reference validator. `validate(obj)` returns a list of `"CODE: message"` strings (empty = valid).
Every rule has a stable code so independent agents (Tasks 11-17) can reimplement and test against the same vectors.
No timezone, unit, mapping method or column is invented here: all values come from the locked protocol (Task 5),
the approved identity ADR (Task 7) and the accepted G-DS verdict A (Task 6).
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

CONTRACT_ID = "twingrid.rack_telemetry"
CONTRACT_VERSION = "1.0.0"
VERSION_RE = re.compile(r"^1\.\d+\.\d+(-draft)?$")

PROVENANCE = ("measured", "derived", "simulated", "synthetic")
STATES = ("observed", "missing", "invalid", "not_reported", "stale")
QUALITY = ("ok", "flagged", "invalid")
TIME_BASIS = ("source_text_undeclared_tz", "utc_instant")
STORAGE_CLASS = ("telemetry_sample", "research_import_file", "derived_series", "fixture_only")
ORIGIN_DB = ("measured", "simulated", "replay")  # the existing database enum; unchanged by this contract
MAPPING_METHODS = ("csv_header_key", "source_image_label", "source_workbook_port_group")
LABEL_EVIDENCE = ("agent_transcribed", "owner_verified", "source_document", "not_applicable")
SITE_STATUS = ("location_not_established", "location_established")
SERVER_STATUS = ("not_present_in_source", "present")
SCOPES = ("rack", "rack_group", "room", "facility", "unattributed")
ROW_DISPOSITIONS = (  # from the locked protocol, [dispositions].row
    "retained",
    "exact_duplicate",
    "conflict_resolved_by_source_rule",
    "conflict_cell_missing",
    "flagged",
    "dropped_with_reason",
)
RECORD_DISPOSITIONS = ("retained", "conflict_resolved_by_source_rule", "conflict_cell_missing", "flagged")
MEASURAND_STATUS = ("sensor_present", "no_sensor_for_asset", "group_channel_only")
WINDOW_STATUS = ("inside_dataset_window", "outside_dataset_window", "not_applicable")
ABSENT_REASONS = ("no_sensor_for_asset", "group_channel_only", "outside_dataset_window", "not_reported_at_time")
ERROR_CODES = ("unknown_facility", "unknown_dataset", "unknown_entity", "stream_required", "bad_request", "internal")
ENVELOPE_KINDS = ("sensor_list", "latest", "history", "rack_view", "error")

PROTOCOL_SHA256_V5 = "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098"
FIXTURE_PREFIX = "synthetic-example."

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
STREAM_RE = re.compile(r"^(live|replay:[0-9a-f-]{36}|import:[a-z0-9.-]{1,57})$")
TS_TEXT_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
TS_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MEASURAND_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

V5_DATASET = "danish-aau-v5"
V5_SENSOR_RE = re.compile(
    r"^danish-aau-v5\.(temperature\.mod[1-9][0-9]*\.ch[1-9][0-9]*|power\.ch[1-3]|velocity\.[1-9][0-9]*)$"
)
V5_ASSET_RE = re.compile(r"^danish-aau-v5\.(rack\.[1-6]|pdu\.ch[1-3]|zone\.serverroom)$")
V5_UNITS = {"temperature": "degC", "power": "W", "air_speed": "m/s"}
V5_DECIMALS = {"temperature": 2, "power": 1, "air_speed": None}  # owner decisions at CK-1 (protocol v1.0.0)
V5_POWER_MEMBERS = {
    "danish-aau-v5.power.ch1": ["1", "2", "3"],
    "danish-aau-v5.power.ch2": ["4", "6"],
    "danish-aau-v5.power.ch3": ["5"],
}

RECORD_KEYS = (
    "contract_version", "record_kind", "facility_id", "site_status", "dataset_id", "stream_id",
    "source_rack_id", "source_server_id", "source_server_status", "asset_external_id", "sensor_external_id",
    "mapping", "time_basis", "ts_source_text", "ts_utc", "measurand", "unit", "value", "value_text",
    "resolution_decimals", "state", "observed", "quality", "reason_code", "age_seconds", "provenance",
    "storage_class", "origin_db", "attribution", "source_ref", "ledger", "derivation", "protocol_ref", "fixture",
)  # fmt: skip


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_str(x: Any) -> bool:
    return isinstance(x, str) and x != ""


def _valid_ts_text(x: Any) -> bool:
    if not isinstance(x, str) or not TS_TEXT_RE.match(x):
        return False
    try:
        datetime.strptime(x, "%Y-%m-%d %H:%M:%S")  # calendar check only; no timezone is attached or implied
    except ValueError:
        return False
    return True


class _Errs(list):
    def add(self, code: str, msg: str) -> None:
        self.append(f"{code}: {msg}")


# ----------------------------------------------------------------------------------------------------------------------
# telemetry record
# ----------------------------------------------------------------------------------------------------------------------
def validate_record(r: Any) -> list[str]:
    e = _Errs()
    if not isinstance(r, dict):
        e.add("E_TYPE", "record must be an object")
        return list(e)
    missing = [k for k in RECORD_KEYS if k not in r]
    extra = [k for k in r if k not in RECORD_KEYS]
    if missing:
        e.add("E_KEYS_MISSING", ", ".join(missing))
    if extra:
        e.add("E_KEYS_UNKNOWN", ", ".join(extra))
    if missing:
        return list(e)

    if not (isinstance(r["contract_version"], str) and VERSION_RE.match(r["contract_version"])):
        e.add("E_VERSION", f"contract_version {r['contract_version']!r}")
    if r["record_kind"] != "telemetry_record":
        e.add("E_KIND", "record_kind must be 'telemetry_record'")
    for k, allowed in (("site_status", SITE_STATUS), ("source_server_status", SERVER_STATUS), ("time_basis", TIME_BASIS),
                       ("state", STATES), ("provenance", PROVENANCE), ("storage_class", STORAGE_CLASS)):  # fmt: skip
        if r[k] not in allowed:
            e.add("E_ENUM", f"{k}={r[k]!r} not in {allowed}")
    if r["quality"] is not None and r["quality"] not in QUALITY:
        e.add("E_ENUM", f"quality={r['quality']!r}")
    if r["origin_db"] is not None and r["origin_db"] not in ORIGIN_DB:
        e.add("E_ENUM", f"origin_db={r['origin_db']!r} (the database enum is unchanged: {ORIGIN_DB})")
    if e:
        return list(e)

    _ids_and_stream(r, e)
    _time(r, e)
    _state_value(r, e)
    _provenance(r, e)
    _attribution(r, e)
    _lineage(r, e)
    _v5_profile(r, e)
    return list(e)


def _ids_and_stream(r, e):
    for k in ("facility_id", "asset_external_id", "sensor_external_id"):
        if not _is_str(r[k]) or (k != "facility_id" and not ID_RE.match(r[k])):
            e.add("E_ID", f"{k}={r[k]!r}")
    if not (isinstance(r["stream_id"], str) and STREAM_RE.match(r["stream_id"])):
        e.add("E_STREAM", f"stream_id={r['stream_id']!r} must be live | replay:<uuid> | import:<dataset_id>")
    ds = r["dataset_id"]
    if ds is None:
        if str(r["stream_id"]).startswith("import:"):
            e.add("E_DATASET_STREAM", "an import stream requires dataset_id")
    elif r["stream_id"] != f"import:{ds}":
        e.add("E_DATASET_STREAM", "dataset_id requires stream_id == 'import:<dataset_id>'")
    if r["measurand"] is None or not (isinstance(r["measurand"], str) and MEASURAND_RE.match(r["measurand"])):
        e.add("E_MEASURAND", f"measurand={r['measurand']!r}")
    if not _is_str(r["unit"]):
        e.add("E_UNIT", "unit must be a non-empty string (use 'not_established' when the source does not state it)")
    syn = r["sensor_external_id"].startswith(FIXTURE_PREFIX) if isinstance(r["sensor_external_id"], str) else False
    if r["provenance"] == "synthetic" and not syn:
        e.add("E_FIXTURE_ID", f"synthetic records use sensor ids starting with {FIXTURE_PREFIX!r}")
    if syn and r["fixture"] is not True:
        e.add("E_FIXTURE_ID", f"ids starting with {FIXTURE_PREFIX!r} appear only on fixture records")
    if r["provenance"] == "synthetic" and r["fixture"] is not True:
        e.add("E_FIXTURE", "synthetic records must carry fixture=true")
    if not isinstance(r["fixture"], bool):
        e.add("E_FIXTURE", "fixture must be boolean")
    elif r["fixture"] and r["provenance"] != "synthetic" and r["value"] is not None:
        e.add("E_FIXTURE_VALUE", "a shape-only (fixture) record that is not synthetic must carry no value")


def _time(r, e):
    tb, txt, utc = r["time_basis"], r["ts_source_text"], r["ts_utc"]
    if tb == "source_text_undeclared_tz":
        if not _valid_ts_text(txt):
            e.add("E_TIME_TEXT", f"ts_source_text {txt!r} must be 'YYYY-MM-DD HH:MM:SS'")
        if utc is not None:
            e.add("E_TIME_UTC_FORBIDDEN", "ts_utc must be null while the source timezone is undeclared")
    else:
        if not (isinstance(utc, str) and TS_UTC_RE.match(utc)):
            e.add("E_TIME_UTC", f"ts_utc {utc!r} must be RFC 3339 with Z or an offset")
        if txt is not None and not _valid_ts_text(txt):
            e.add("E_TIME_TEXT", f"ts_source_text {txt!r}")


def _state_value(r, e):
    st, v, vt, q, reason, age = (
        r["state"],
        r["value"],
        r["value_text"],
        r["quality"],
        r["reason_code"],
        r["age_seconds"],
    )
    if reason is not None and not (isinstance(reason, str) and REASON_RE.match(reason)):
        e.add("E_REASON", f"reason_code {reason!r}")
    if v is not None and not _num(v):
        e.add("E_VALUE", f"value must be a finite number or null, got {v!r}")
        return
    if r["observed"] is not (v is not None):
        e.add("E_OBSERVED", "observed must equal (value is not null)")
    if st != "stale" and age is not None:
        e.add("E_AGE", "age_seconds only on state 'stale'")
    if st == "observed":
        if v is None:
            e.add("E_STATE_VALUE", "observed requires a value")
        if q not in ("ok", "flagged"):
            e.add("E_STATE_QUALITY", "observed requires quality ok or flagged (out-of-range is flagged, never clipped)")
        if (q == "flagged") != (reason is not None):
            e.add("E_STATE_REASON", "flagged requires reason_code; ok forbids it")
    elif st in ("missing", "not_reported"):
        if v is not None or vt is not None:
            e.add("E_STATE_VALUE", f"{st} carries no value and no value_text (never imputed)")
        if q is not None:
            e.add("E_STATE_QUALITY", f"{st} has quality null")
        if reason is None:
            e.add("E_STATE_REASON", f"{st} requires reason_code")
    elif st == "invalid":
        if q != "invalid":
            e.add("E_STATE_QUALITY", "invalid requires quality 'invalid'")
        if reason is None:
            e.add("E_STATE_REASON", "invalid requires reason_code")
    elif st == "stale":
        if v is None or q not in ("ok", "flagged"):
            e.add("E_STATE_VALUE", "stale carries the last observed value with its quality")
        if not (_num(age) and age > 0):
            e.add("E_AGE", "stale requires age_seconds > 0")
        if str(r["stream_id"]).startswith("import:") or r["time_basis"] != "utc_instant":
            e.add(
                "E_STALE_SCOPE", "stale applies only to live/replay data with a UTC instant, never to imported history"
            )
    dec = r["resolution_decimals"]
    if dec is not None and not (_int(dec) and 0 <= dec <= 12):
        e.add("E_RESOLUTION", f"resolution_decimals {dec!r}")
    if vt is not None:
        if not (isinstance(vt, str) and re.match(r"^-?\d+(\.\d+)?$", vt)):
            e.add("E_VALUE_TEXT", f"value_text {vt!r}")
        else:
            if v is None or float(vt) != v:
                e.add("E_VALUE_TEXT", "value_text must parse to value exactly")
            if dec is not None and (len(vt.split(".")[1]) if "." in vt else 0) != dec:
                e.add("E_VALUE_TEXT", f"value_text must have exactly {dec} decimals")


def _provenance(r, e):
    p, sc, od = r["provenance"], r["storage_class"], r["origin_db"]
    if p == "measured":
        if sc not in ("telemetry_sample", "research_import_file"):
            e.add("E_STORAGE", "measured -> telemetry_sample or research_import_file")
        if sc == "telemetry_sample" and od not in ("measured", "replay"):
            e.add("E_ORIGIN", "measured in telemetry_sample uses origin 'measured' or 'replay'")
    elif p == "simulated":
        if sc != "telemetry_sample" or od != "simulated":
            e.add("E_ORIGIN", "simulated -> telemetry_sample with origin 'simulated'")
    elif p == "derived":
        if sc != "derived_series" or od is not None:
            e.add(
                "E_STORAGE",
                "derived values are never inserted into telemetry_sample: storage derived_series, origin_db null",
            )
    else:  # synthetic
        if sc != "fixture_only" or od is not None:
            e.add("E_STORAGE", "synthetic -> fixture_only, origin_db null")
    if sc == "research_import_file" and od is not None:
        e.add("E_ORIGIN", "research_import_file records have origin_db null")
    d = r["derivation"]
    if p != "derived":
        if d is not None:
            e.add("E_DERIVATION", "derivation only on derived records")
        return
    keys = (
        "formula_id",
        "formula_text",
        "inputs",
        "input_scopes",
        "mapping_id",
        "mapping_version",
        "code_version",
        "method_approval_ref",
    )
    if not isinstance(d, dict) or any(k not in d for k in keys) or set(d) - set(keys):
        e.add("E_DERIVATION", f"derived records require derivation with exactly {keys}")
        return
    if not all(
        _is_str(d[k]) for k in ("formula_id", "formula_text", "mapping_id", "code_version", "method_approval_ref")
    ) or not _int(d["mapping_version"]):
        e.add("E_DERIVATION", "derivation text fields must be non-empty and mapping_version an integer")
    ins = d["inputs"]
    if not (
        isinstance(ins, list)
        and ins
        and all(isinstance(i, dict) and _is_str(i.get("sensor_external_id")) and "source_ref_key" in i for i in ins)
    ):
        e.add("E_DERIVATION", "inputs must be a non-empty list of {sensor_external_id, source_ref_key}")
    scopes = d["input_scopes"]
    if not (
        isinstance(scopes, list)
        and scopes
        and all(s in SCOPES for s in scopes)
        and isinstance(ins, list)
        and len(scopes) == len(ins)
    ):
        e.add("E_DERIVATION", "input_scopes must list one valid scope per input")
    elif "rack_group" in scopes and r["attribution"]["scope"] != "rack_group":
        e.add(
            "E_GROUP_SPLIT", "a derived value computed from a group input stays rack_group; it never becomes per-rack"
        )


def _attribution(r, e):
    a = r["attribution"]
    if not (isinstance(a, dict) and set(a) == {"scope", "member_source_rack_ids", "split_allowed"}):
        e.add("E_ATTRIBUTION", "attribution requires exactly scope, member_source_rack_ids, split_allowed")
        return
    scope, mem = a["scope"], a["member_source_rack_ids"]
    if scope not in SCOPES or not (isinstance(mem, list) and all(_is_str(m) and m.isdigit() for m in mem)):
        e.add("E_ATTRIBUTION", "scope or member list invalid")
        return
    if a["split_allowed"] is not False:
        e.add("E_GROUP_SPLIT", "split_allowed must always be false")
    if len(set(mem)) != len(mem) or mem != sorted(mem, key=int):
        e.add("E_ATTRIBUTION", "members must be unique and ascending")
    if scope == "rack":
        if len(mem) != 1 or r["source_rack_id"] != mem[0]:
            e.add("E_ATTRIBUTION", "scope rack: exactly one member, equal to source_rack_id")
    elif scope == "rack_group":
        if len(mem) < 2 or r["source_rack_id"] is not None:
            e.add("E_GROUP_SPLIT", "scope rack_group: at least two members and source_rack_id null (no per-rack field)")
    elif mem or r["source_rack_id"] is not None:
        e.add("E_ATTRIBUTION", f"scope {scope} has no source rack")
    if r["source_server_id"] is not None and r["source_server_status"] != "present":
        e.add("E_SERVER", "source_server_id requires source_server_status 'present'")
    if r["source_server_status"] == "present" and r["source_server_id"] is None:
        e.add("E_SERVER", "status 'present' requires source_server_id")


def _lineage(r, e):
    imp = r["provenance"] == "measured" and str(r["stream_id"]).startswith("import:")
    sr, lg, mp, pr = r["source_ref"], r["ledger"], r["mapping"], r["protocol_ref"]
    if imp:
        for name, val in (("source_ref", sr), ("ledger", lg), ("mapping", mp), ("protocol_ref", pr)):
            if val is None:
                e.add("E_LINEAGE", f"measured import records require {name}")
    if r["provenance"] == "derived" and sr is not None:
        e.add("E_LINEAGE", "derived records cite inputs in derivation, not source_ref")
    if sr is not None:
        keys = {"file", "column", "row_ordinal", "row_numbering", "ts_text", "key", "file_sha256"}
        if not (isinstance(sr, dict) and set(sr) == keys):
            e.add("E_SOURCE_REF", f"source_ref requires exactly {sorted(keys)}")
        else:
            if not (_is_str(sr["file"]) and _is_str(sr["column"]) and "|" not in sr["file"] + sr["column"]):
                e.add("E_SOURCE_REF", "file/column must be non-empty without '|'")
            if sr["row_ordinal"] is not None and not (_int(sr["row_ordinal"]) and sr["row_ordinal"] >= 1):
                e.add("E_SOURCE_REF", "row_ordinal is a 1-based integer or null")
            if sr["row_numbering"] not in ("data_row_ordinal_excluding_header", "unspecified"):
                e.add("E_SOURCE_REF", "row_numbering enum")
            if sr["ts_text"] != r["ts_source_text"]:
                e.add("E_SOURCE_REF", "source_ref.ts_text must equal ts_source_text")
            if sr["key"] != f"{sr['file']}|{sr['column']}|{sr['ts_text']}":
                e.add("E_SOURCE_REF", "key must be 'file|column|ts_text'")
            if sr["file_sha256"] is not None and not (
                isinstance(sr["file_sha256"], str) and SHA_RE.match(sr["file_sha256"])
            ):
                e.add("E_SOURCE_REF", "file_sha256 must be 64 lowercase hex or null")
    if lg is not None:
        if not (isinstance(lg, dict) and set(lg) == {"row_disposition", "group_size", "group_ref"}):
            e.add("E_LEDGER", "ledger requires exactly row_disposition, group_size, group_ref")
        else:
            if lg["row_disposition"] not in RECORD_DISPOSITIONS:
                e.add(
                    "E_LEDGER",
                    f"record disposition must be one of {RECORD_DISPOSITIONS} (exact_duplicate / dropped rows are ledger entries, not records)",
                )
            if not (_int(lg["group_size"]) and lg["group_size"] >= 1):
                e.add("E_LEDGER", "group_size >= 1")
            if r["reason_code"] == "conflict_unresolved_tie" and not (
                r["state"] == "missing"
                and lg["row_disposition"] == "conflict_cell_missing"
                and _int(lg["group_size"])
                and lg["group_size"] >= 2
            ):
                e.add(
                    "E_LEDGER",
                    "conflict_unresolved_tie => state missing, disposition conflict_cell_missing, group_size >= 2",
                )
            if (lg["row_disposition"] == "flagged") != (r["quality"] == "flagged"):
                e.add("E_LEDGER", "disposition 'flagged' <=> quality 'flagged'")
    if mp is not None:
        keys = {
            "mapping_id",
            "mapping_version",
            "method",
            "label_evidence",
            "valid_time_status",
            "applied_uniformly_over_window",
        }
        if not (isinstance(mp, dict) and set(mp) == keys):
            e.add("E_MAPPING", f"mapping requires exactly {sorted(keys)}")
        else:
            if not (_is_str(mp["mapping_id"]) and _int(mp["mapping_version"]) and mp["mapping_version"] >= 1):
                e.add("E_MAPPING", "mapping_id non-empty, mapping_version >= 1")
            if mp["method"] not in MAPPING_METHODS:
                e.add("E_MAPPING", f"method {mp['method']!r} not in {MAPPING_METHODS}")
            if mp["label_evidence"] not in LABEL_EVIDENCE:
                e.add("E_MAPPING", "label_evidence enum")
            if mp["valid_time_status"] not in ("not_established", "established") or not isinstance(
                mp["applied_uniformly_over_window"], bool
            ):
                e.add("E_MAPPING", "valid_time_status / applied_uniformly_over_window")
    if pr is not None and not (
        isinstance(pr, dict)
        and set(pr) == {"protocol_sha256"}
        and isinstance(pr["protocol_sha256"], str)
        and SHA_RE.match(pr["protocol_sha256"])
    ):
        e.add("E_PROTOCOL_REF", "protocol_ref requires exactly {protocol_sha256: 64 hex}")


def _v5_profile(r, e):
    if r["dataset_id"] != V5_DATASET:
        return
    sid, aid, m = r["sensor_external_id"], r["asset_external_id"], r["measurand"]
    if not V5_SENSOR_RE.match(sid):
        e.add("E_V5_SENSOR_ID", f"{sid!r}")
    if not V5_ASSET_RE.match(aid):
        e.add("E_V5_ASSET_ID", f"{aid!r}")
    if r["source_server_id"] is not None or r["source_server_status"] != "not_present_in_source":
        e.add("E_V5_SERVER", "verdict A: no server data; source_server_id null, status not_present_in_source")
    if r["time_basis"] != "source_text_undeclared_tz":
        e.add("E_V5_TIME", "the v5 timezone is undeclared; ts_utc stays null (amend the protocol first)")
    if r["site_status"] != "location_not_established":
        e.add("E_V5_SITE", "v5 site location is not established")
    if m not in V5_UNITS:
        e.add("E_V5_MEASURAND", f"measurand must be one of {sorted(V5_UNITS)}")
    else:
        if r["unit"] != V5_UNITS[m]:
            e.add("E_V5_UNIT", f"{m} unit must be {V5_UNITS[m]!r}")
        if r["resolution_decimals"] != V5_DECIMALS[m]:
            e.add(
                "E_V5_RESOLUTION",
                f"{m} resolution_decimals must be {V5_DECIMALS[m]} (owner decision, not a sensor specification)",
            )
    if r["provenance"] == "measured":
        if (r["protocol_ref"] or {}).get("protocol_sha256") != PROTOCOL_SHA256_V5:
            e.add("E_V5_PROTOCOL", "measured v5 records cite the locked protocol hash")
        mp = r["mapping"] or {}
        if mp.get("valid_time_status") != "not_established" or mp.get("applied_uniformly_over_window") is not True:
            e.add(
                "E_V5_MAPPING", "v5 mappings are not time-valid; applied uniformly over the window (owner answer O-1)"
            )
        if m == "temperature" and r["attribution"]["scope"] == "rack" and mp.get("method") != "source_image_label":
            e.add("E_V5_MAPPING", "rack association of temperature probes comes from source_image_label")
        if m == "power" and mp.get("method") != "source_workbook_port_group":
            e.add("E_V5_MAPPING", "power group membership comes from source_workbook_port_group")
    if m == "power" and sid in V5_POWER_MEMBERS:
        want = V5_POWER_MEMBERS[sid]
        scope = "rack_group" if len(want) > 1 else "rack"
        if r["attribution"]["scope"] != scope or r["attribution"]["member_source_rack_ids"] != want:
            e.add(
                "E_V5_POWER_GROUP",
                f"{sid} has scope {scope} and members {want}; a group channel is never split per rack",
            )
    if m == "temperature" and r["attribution"]["scope"] == "rack_group":
        e.add("E_V5_ATTRIBUTION", "temperature probes are never group-attributed")


# ----------------------------------------------------------------------------------------------------------------------
# cleaning-ledger entry (one per raw row; exact duplicates and drops live here, not in records)
# ----------------------------------------------------------------------------------------------------------------------
LEDGER_KEYS = ("contract_version", "record_kind", "dataset_id", "file", "row_ordinal", "row_numbering", "ts_source_text", "disposition", "reason_code", "group_size", "protocol_sha256")  # fmt: skip


def validate_ledger_entry(x: Any) -> list[str]:
    e = _Errs()
    if not isinstance(x, dict) or set(x) != set(LEDGER_KEYS):
        e.add("E_KEYS", f"ledger entry requires exactly {LEDGER_KEYS}")
        return list(e)
    if x["record_kind"] != "ledger_entry" or not VERSION_RE.match(str(x["contract_version"])):
        e.add("E_KIND", "record_kind 'ledger_entry' and a valid contract_version")
    if x["disposition"] not in ROW_DISPOSITIONS:
        e.add("E_ENUM", f"disposition {x['disposition']!r}")
    if not (_int(x["row_ordinal"]) and x["row_ordinal"] >= 1) or x["row_numbering"] not in (
        "data_row_ordinal_excluding_header",
        "unspecified",
    ):
        e.add("E_LEDGER", "row_ordinal / row_numbering")
    if not _valid_ts_text(x["ts_source_text"]):
        e.add("E_TIME_TEXT", "ts_source_text")
    if x["disposition"] in (
        "dropped_with_reason",
        "flagged",
        "conflict_cell_missing",
        "conflict_resolved_by_source_rule",
    ) and not (isinstance(x["reason_code"], str) and REASON_RE.match(x["reason_code"])):
        e.add("E_STATE_REASON", f"{x['disposition']} requires reason_code")
    if x["disposition"] == "exact_duplicate" and not (_int(x["group_size"]) and x["group_size"] >= 2):
        e.add("E_LEDGER", "exact_duplicate requires group_size >= 2")
    if not (isinstance(x["protocol_sha256"], str) and SHA_RE.match(x["protocol_sha256"])):
        e.add("E_PROTOCOL_REF", "protocol_sha256")
    return list(e)


# ----------------------------------------------------------------------------------------------------------------------
# API envelopes
# ----------------------------------------------------------------------------------------------------------------------
def _envelope_common(x, e):
    for k in ("contract_version", "kind", "facility_id", "dataset_id", "stream_id"):
        if k not in x:
            e.add("E_KEYS_MISSING", k)
    if e:
        return False
    if not VERSION_RE.match(str(x["contract_version"])) or x["kind"] not in ENVELOPE_KINDS:
        e.add("E_KIND", "contract_version / kind")
    if not _is_str(x["facility_id"]):
        e.add("E_ID", "facility_id is explicit and never defaulted")
    if not (isinstance(x["stream_id"], str) and STREAM_RE.match(x["stream_id"])):
        e.add("E_STREAM", "stream_id is explicit (no default; never 'live' for imports)")
    elif (
        x["dataset_id"] is None
        and x["stream_id"].startswith("import:")
        or (x["dataset_id"] is not None and x["stream_id"] != f"import:{x['dataset_id']}")
    ):
        e.add("E_DATASET_STREAM", "dataset_id and stream_id disagree")
    return not e


def _rec_checks(rec, x, e, sensor=None):
    errs = validate_record(rec)
    for m in errs:
        e.add("E_RECORD", m)
    if not errs:
        if (rec["facility_id"], rec["dataset_id"], rec["stream_id"]) != (
            x["facility_id"],
            x["dataset_id"],
            x["stream_id"],
        ):
            e.add("E_ENVELOPE_MISMATCH", "record facility/dataset/stream differ from the envelope")
        if sensor is not None and rec["sensor_external_id"] != sensor:
            e.add("E_ENVELOPE_MISMATCH", "record sensor differs from the envelope sensor")


def validate_envelope(x: Any) -> list[str]:
    e = _Errs()
    if not isinstance(x, dict):
        e.add("E_TYPE", "envelope must be an object")
        return list(e)
    if x.get("kind") == "error":
        keys = {"contract_version", "kind", "status", "code", "message", "facility_id", "dataset_id", "stream_id"}
        if (
            set(x) != keys
            or x["code"] not in ERROR_CODES
            or not (_int(x["status"]) and 400 <= x["status"] <= 599)
            or not _is_str(x["message"])
        ):
            e.add("E_ERROR", f"error envelope requires exactly {sorted(keys)}, a known code and a 4xx/5xx status")
        return list(e)
    if not _envelope_common(x, e):
        return list(e)
    kind = x["kind"]
    if kind == "sensor_list":
        ik = {
            "sensor_external_id",
            "asset_external_id",
            "measurand",
            "unit",
            "mapping_id",
            "mapping_version",
            "method",
            "measurand_status",
        }
        if set(x) != {
            "contract_version",
            "kind",
            "facility_id",
            "dataset_id",
            "stream_id",
            "count",
            "items",
        } or not isinstance(x["items"], list):
            e.add("E_KEYS", "sensor_list requires count and items")
        else:
            if x["count"] != len(x["items"]):
                e.add("E_COUNT", "count must equal len(items)")
            for it in x["items"]:
                if (
                    not (isinstance(it, dict) and set(it) == ik)
                    or it["measurand_status"] not in MEASURAND_STATUS
                    or it["method"] not in MAPPING_METHODS
                ):
                    e.add("E_ITEM", f"item requires exactly {sorted(ik)} with valid enums")
    elif kind == "latest":
        keys = {
            "contract_version",
            "kind",
            "facility_id",
            "dataset_id",
            "stream_id",
            "sensor_external_id",
            "measurand_status",
            "window_status",
            "record_absent_reason",
            "record",
        }
        if set(x) != keys:
            e.add("E_KEYS", f"latest requires exactly {sorted(keys)}")
        else:
            if x["measurand_status"] not in MEASURAND_STATUS or x["window_status"] not in WINDOW_STATUS:
                e.add("E_ENUM", "measurand_status / window_status")
            if x["record"] is None:
                if x["record_absent_reason"] not in ABSENT_REASONS:
                    e.add("E_ABSENT", f"an absent record needs record_absent_reason in {ABSENT_REASONS}")
            else:
                if x["record_absent_reason"] is not None or x["measurand_status"] != "sensor_present":
                    e.add("E_ABSENT", "a present record has no absent reason and measurand_status sensor_present")
                _rec_checks(x["record"], x, e, x["sensor_external_id"])
    elif kind == "history":
        keys = {
            "contract_version",
            "kind",
            "facility_id",
            "dataset_id",
            "stream_id",
            "sensor_external_id",
            "from_source_text",
            "to_source_text",
            "include_invalid",
            "include_states",
            "count",
            "page",
            "records",
        }
        if set(x) != keys or not isinstance(x["records"], list):
            e.add("E_KEYS", f"history requires exactly {sorted(keys)}")
        else:
            for b in ("from_source_text", "to_source_text"):
                if x[b] is not None and not _valid_ts_text(x[b]):
                    e.add(
                        "E_TIME_TEXT",
                        f"{b} is naive source text or null (no UTC bounds while the timezone is undeclared)",
                    )
            if not isinstance(x["include_invalid"], bool) or not (
                isinstance(x["include_states"], list)
                and x["include_states"]
                and all(s in STATES for s in x["include_states"])
            ):
                e.add("E_HISTORY", "include_invalid (bool) and include_states (non-empty list of states) are explicit")
            pg = x["page"]
            if not (
                isinstance(pg, dict)
                and set(pg) == {"limit", "next_cursor"}
                and _int(pg["limit"])
                and 1 <= pg["limit"] <= 1000
                and (pg["next_cursor"] is None or _is_str(pg["next_cursor"]))
            ):
                e.add("E_HISTORY", "page requires limit 1..1000 and next_cursor")
            if x["count"] != len(x["records"]):
                e.add("E_COUNT", "count must equal len(records)")
            last = None
            for rec in x["records"]:
                _rec_checks(rec, x, e, x["sensor_external_id"])
                if isinstance(rec, dict) and not validate_record(rec):
                    t = rec["ts_source_text"] or rec["ts_utc"]
                    if last is not None and t <= last:
                        e.add("E_ORDER", "records must be strictly ascending by time with no duplicate instants")
                    last = t
                    if rec["state"] == "invalid" and not x["include_invalid"]:
                        e.add("E_HISTORY", "invalid records only when include_invalid is true")
                    if rec["state"] not in x["include_states"]:
                        e.add("E_HISTORY", "record state not in include_states")
    elif kind == "rack_view":
        keys = {
            "contract_version",
            "kind",
            "facility_id",
            "dataset_id",
            "stream_id",
            "source_rack_id",
            "asset_external_id",
            "temperature_sensors",
            "power",
        }
        if set(x) != keys or not isinstance(x["temperature_sensors"], list):
            e.add("E_KEYS", f"rack_view requires exactly {sorted(keys)}")
        else:
            for t in x["temperature_sensors"]:
                tk = {"sensor_external_id", "source_label", "source_position_word", "label_evidence", "record"}
                if not (isinstance(t, dict) and set(t) == tk) or t["label_evidence"] not in LABEL_EVIDENCE:
                    e.add("E_ITEM", f"temperature sensor entry requires exactly {sorted(tk)}")
                elif t["record"] is not None:
                    _rec_checks(t["record"], x, e, t["sensor_external_id"])
            p = x["power"]
            if not isinstance(p, dict) or p.get("kind") not in ("group_pointer", "single_rack_port", "not_available"):
                e.add("E_POWER", "power.kind must be group_pointer | single_rack_port | not_available")
            elif p["kind"] == "group_pointer":
                if (
                    set(p) != {"kind", "sensor_external_id", "member_source_rack_ids", "value", "split_allowed"}
                    or p["value"] is not None
                    or p["split_allowed"] is not False
                    or x["source_rack_id"] not in p["member_source_rack_ids"]
                    or len(p["member_source_rack_ids"]) < 2
                ):
                    e.add(
                        "E_GROUP_SPLIT",
                        "a rack view of a group channel shows a pointer with value null, split_allowed false and the full member list",
                    )
            elif p["kind"] == "single_rack_port":
                if set(p) != {"kind", "record"}:
                    e.add("E_POWER", "single_rack_port requires exactly kind and record")
                else:
                    _rec_checks(p["record"], x, e)
                    if not validate_record(p["record"]) and (
                        p["record"]["attribution"]["scope"] != "rack"
                        or p["record"]["source_rack_id"] != x["source_rack_id"]
                    ):
                        e.add("E_GROUP_SPLIT", "rack-level power is allowed only for a single-rack port of this rack")
            elif set(p) != {"kind", "reason"} or not _is_str(p["reason"]):
                e.add("E_POWER", "not_available requires kind and reason")
    return list(e)


def validate(obj: Any) -> list[str]:
    """Dispatch on `record_kind` / `kind`."""
    if isinstance(obj, dict) and obj.get("record_kind") == "ledger_entry":
        return validate_ledger_entry(obj)
    if isinstance(obj, dict) and "record_kind" in obj:
        return validate_record(obj)
    return validate_envelope(obj)
