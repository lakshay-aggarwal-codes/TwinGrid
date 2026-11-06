"""Validation of the identity mapping document. Returns ``CODE: message`` strings; an empty list means valid.

Rules that must never be loosened: every entity maps exactly once; every mapped entity has evidence and a stable id;
a group channel is never attributed to one rack and never split; temperature probes are never group-attributed;
no mapping claims time validity; no inlet/outlet/supply/return word is invented; no server entity exists (verdict A).
Contract constants are reused from the approved Task 8 module (read-only), not copied.
"""

from __future__ import annotations

import re
from typing import Any

from ..contract.telemetry_contract import (
    LABEL_EVIDENCE,
    MAPPING_METHODS,
    PROTOCOL_SHA256_V5,
    SCOPES,
    SHA_RE,
    V5_ASSET_RE,
    V5_DATASET,
    V5_DECIMALS,
    V5_POWER_MEMBERS,
    V5_SENSOR_RE,
    V5_UNITS,
)

PREFIX = V5_DATASET + "."
TOP_KEYS = {
    "mapping_file",
    "time",
    "site",
    "evidence_sources",
    "racks",
    "power_ports",
    "zone",
    "entities",
    "excluded_items",
}
FILE_KEYS = {
    "name", "mapping_version", "status", "decided_by", "decided_on", "dataset_id", "contract_version", "protocol_sha256",
    "task7_adr_sha256_lf_normalised", "task7_amendment", "authority",
}  # fmt: skip
ENTITY_KEYS = {
    "entity_id", "source_entity_class", "source_column", "source_file_family", "sensor_external_id", "reserved_id",
    "mapping_id", "mapping_version", "mapping_status", "tier", "mapping_state", "load_in_v1", "asset_external_id",
    "target_asset_external_ids", "source_rack_id", "cardinality", "attribution", "measurand", "unit",
    "resolution_decimals", "method", "label_evidence", "evidence_status", "evidence_refs", "source_label",
    "source_position_word", "valid_time_status", "applied_uniformly_over_window", "notes",
}  # fmt: skip
OPTIONAL_ENTITY_KEYS = {"verification_ref"}
CLASSES = (
    "rack_probe", "cooling_unit_probe", "room_gradient_probe", "power_channel", "air_speed_channel",
    "surrounding_temperature", "ventilation",
)  # fmt: skip
TIERS = ("tier1", "tier2", "deferred")
STATES = ("mapped", "mapped_partial", "unmapped", "not_applicable")
POSITION_WORDS = {
    "rack_probe": {"front", "back"},
    "cooling_unit_probe": {"cooling unit"},
    "room_gradient_probe": {"room"},
    "power_channel": {"power measurement port"},
    "air_speed_channel": {"room"},
    "surrounding_temperature": {"room boundary"},
    "ventilation": {"ahu or damper"},
}
FORBIDDEN_WORDS = ("inlet", "outlet", "supply", "return")  # interpretation words the source never states
DEMO_ID_RE = re.compile(r"^(zone-\d+|facility-level|fac\d+\.)")
RACK_LABEL_RE = re.compile(r"^Rack ([1-6]) (front|back)\b")
TEMP_COL_RE = re.compile(r"^Temperature mod ([1-9]\d*) ch ([1-9]\d*)$")
FAMILY_FOR_CLASS = {
    "rack_probe": "temperature_power", "cooling_unit_probe": "temperature_power",
    "room_gradient_probe": "temperature_power", "power_channel": "temperature_power",
    "air_speed_channel": "air_speed", "surrounding_temperature": "surrounding_temperatures",
    "ventilation": "ventilation",
}  # fmt: skip
EXPECTED = {  # Task 7 section 3.3 / Task 3 register, v5 only
    "classes": {
        "rack_probe": 37, "cooling_unit_probe": 6, "room_gradient_probe": 5, "power_channel": 3,
        "air_speed_channel": 16, "surrounding_temperature": 6, "ventilation": 6,
    },
    "probes_per_rack": {"1": 3, "2": 3, "3": 3, "4": 3, "5": 22, "6": 3},
    "front_back": (9, 28),
    "total": 79,
}  # fmt: skip


def normalise_header(h: str) -> str:
    """Task 7 rule 5: lowercase, each run outside [a-z0-9] becomes '-', trim '-'."""
    return re.sub(r"[^a-z0-9]+", "-", h.lower()).strip("-")


def _schema_columns() -> dict[str, set[str]]:
    from ..adapter.schema import FILE_SPECS

    out: dict[str, set[str]] = {}
    for s in FILE_SPECS:
        out.setdefault(s.family, set()).update(s.measurement_columns)
    return out


VERIFICATION_REF_KEYS = {"sheet_file", "sheet_sha256", "row_id", "confirmed_on"}
ROW_ID_RE = re.compile(r"^(T(0[1-9]|[1-3][0-9]|4[0-8])|V(0[1-9]|1[0-6]))$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_verification_ref(eid, vref, srcs, add):
    """An owner_verified entity must name the confirmation sheet, its 64-hex SHA-256, its row id and the date."""
    if not (isinstance(vref, dict) and set(vref) == VERIFICATION_REF_KEYS):
        add("M_LABEL", f"{eid}: verification_ref needs exactly {sorted(VERIFICATION_REF_KEYS)}")
        return
    if not (isinstance(vref["sheet_file"], str) and vref["sheet_file"]):
        add("M_LABEL", f"{eid}: verification_ref.sheet_file must name the owner sheet")
    if not (isinstance(vref["sheet_sha256"], str) and SHA_RE.match(vref["sheet_sha256"])):
        add("M_LABEL", f"{eid}: verification_ref.sheet_sha256 must be 64 hex characters")
    if not (isinstance(vref["row_id"], str) and ROW_ID_RE.match(vref["row_id"])):
        add("M_LABEL", f"{eid}: verification_ref.row_id must be T01-T48 or V01-V16")
    if not (isinstance(vref["confirmed_on"], str) and DATE_RE.match(vref["confirmed_on"])):
        add("M_LABEL", f"{eid}: verification_ref.confirmed_on must be a YYYY-MM-DD date")
    src = srcs.get("owner_label_confirmation") if isinstance(srcs, dict) else None
    if not (
        isinstance(src, dict) and src.get("sha256") == vref["sheet_sha256"] and src.get("file") == vref["sheet_file"]
    ):
        add(
            "M_LABEL",
            f"{eid}: verification_ref must match the owner_label_confirmation evidence source (file and SHA-256)",
        )


def validate_mapping(doc: Any, *, schema_columns: dict[str, set[str]] | None = None) -> list[str]:
    e: list[str] = []

    def add(code: str, msg: str) -> None:
        e.append(f"{code}: {msg}")

    if not isinstance(doc, dict) or set(doc) != TOP_KEYS:
        add("M_KEYS", f"top level requires exactly {sorted(TOP_KEYS)}")
        return e
    mf = doc["mapping_file"]
    if not isinstance(mf, dict) or set(mf) != FILE_KEYS:
        add("M_KEYS", f"mapping_file requires exactly {sorted(FILE_KEYS)}")
        return e
    ver = mf["mapping_version"]
    if not (isinstance(ver, int) and not isinstance(ver, bool) and ver >= 1):
        add("M_VERSION", "mapping_version must be an integer >= 1")
    if mf["dataset_id"] != V5_DATASET:
        add("M_DATASET", f"dataset_id must be {V5_DATASET!r}")
    if mf["protocol_sha256"] != PROTOCOL_SHA256_V5:
        add("M_PROTOCOL", "protocol_sha256 must be the locked v5 protocol hash")
    if mf["status"] not in ("ready_for_review", "approved", "superseded", "withdrawn"):
        add("M_STATUS", f"status {mf['status']!r}")
    if mf["status"] == "approved" and not (mf["decided_by"] and mf["decided_on"]):
        add("M_STATUS", "an approved mapping records decided_by and decided_on (owner decision trail)")
    if not (
        isinstance(mf["task7_adr_sha256_lf_normalised"], str) and SHA_RE.match(mf["task7_adr_sha256_lf_normalised"])
    ):
        add("M_STATUS", "task7_adr_sha256_lf_normalised must be a 64-hex SHA-256")
    t, s = doc["time"], doc["site"]
    if not (
        isinstance(t, dict)
        and t.get("valid_time_status") == "not_established"
        and t.get("applied_uniformly_over_window") is True
    ):
        add("M_TIME", "v5 mappings are not time-valid and are applied uniformly over the window (owner answer O-1)")
    if not (
        isinstance(s, dict)
        and s.get("site_status") == "location_not_established"
        and s.get("server_status") == "not_present_in_source"
    ):
        add(
            "M_SITE",
            "site_status location_not_established and server_status not_present_in_source (verdict A, no server data)",
        )

    # evidence sources
    srcs = doc["evidence_sources"]
    if not (isinstance(srcs, dict) and srcs):
        add("M_EVIDENCE", "evidence_sources must be a non-empty object")
        srcs = {}
    for k, v in srcs.items():
        if not (isinstance(v, dict) and isinstance(v.get("description"), str) and v["description"]):
            add("M_EVIDENCE", f"evidence source {k!r} needs a description")
            continue
        shas = []
        if "sha256" in v:
            shas += list(v["sha256"].values()) if isinstance(v["sha256"], dict) else [v["sha256"]]
        if "container_sha256" in v:
            shas.append(v["container_sha256"])
        for h in shas:
            if not (isinstance(h, str) and SHA_RE.match(h)):
                add("M_EVIDENCE", f"evidence source {k!r} has an invalid SHA-256")

    # assets
    rack_ids = {}
    for r in doc["racks"]:
        aid = r.get("asset_external_id", "")
        if not V5_ASSET_RE.match(str(aid)) or not str(aid).startswith(PREFIX + "rack."):
            add("M_ID", f"rack asset id {aid!r}")
        rack_ids[str(r.get("source_rack_id"))] = aid
        if aid != f"{PREFIX}rack.{r.get('source_rack_id')}" or r.get("asset_type") != "rack":
            add("M_RACK", f"rack entry {aid!r} must be {PREFIX}rack.<N> of type rack with matching source_rack_id")
        if not r.get("evidence_refs"):
            add("M_EVIDENCE", f"rack {aid!r} has no evidence_refs")
        for ref in r.get("evidence_refs", []):
            if ref.get("source") not in srcs:
                add("M_EVIDENCE", f"rack {aid!r} cites unknown evidence source {ref.get('source')!r}")
    if sorted(rack_ids) != ["1", "2", "3", "4", "5", "6"] or len(doc["racks"]) != 6:
        add("M_RACK", "exactly racks 1..6 are required")
    port_ids = {p.get("asset_external_id") for p in doc["power_ports"]}
    if port_ids != {f"{PREFIX}pdu.ch{n}" for n in (1, 2, 3)} or any(
        p.get("asset_type") != "pdu" for p in doc["power_ports"]
    ):
        add("M_POWER", "exactly the power-port assets pdu.ch1..ch3 of type pdu are required")
    z = doc["zone"]
    if not (
        isinstance(z, dict)
        and z.get("asset_external_id") == PREFIX + "zone.serverroom"
        and z.get("asset_type") == "zone"
    ):
        add("M_ROOM", "room-scope asset must be danish-aau-v5.zone.serverroom of type zone")
    for a in (*doc["racks"], *doc["power_ports"], z):
        n = str(a.get("name", "")) if isinstance(a, dict) else ""
        if any(w in n.lower() for w in FORBIDDEN_WORDS):
            add("M_NAMING", f"asset name {n!r} uses an interpretation word the source never states")

    ents = doc["entities"]
    if not isinstance(ents, list):
        add("M_KEYS", "entities must be a list")
        return e
    seen: dict[str, set[str]] = {k: set() for k in ("entity", "sensor", "mapping", "reserved", "column")}
    class_counts: dict[str, int] = {}
    probes_per_rack: dict[str, int] = {}
    front_back = {"front": 0, "back": 0}
    cols_by_family: dict[str, set[str]] = {}
    for x in ents:
        if not isinstance(x, dict) or not ENTITY_KEYS <= set(x) or set(x) - ENTITY_KEYS - OPTIONAL_ENTITY_KEYS:
            add("M_KEYS", f"entity requires exactly {sorted(ENTITY_KEYS)} (+ optional {sorted(OPTIONAL_ENTITY_KEYS)})")
            continue
        eid = x["entity_id"]
        cls = x["source_entity_class"]
        class_counts[cls] = class_counts.get(cls, 0) + 1
        if cls not in CLASSES:
            add("M_ENUM", f"{eid}: class {cls!r}")
            continue
        if "server" in cls:
            add("M_SERVER", f"{eid}: verdict A has no server entity")
        if x["tier"] not in TIERS or x["mapping_state"] not in STATES:
            add("M_ENUM", f"{eid}: tier/mapping_state")
        if x["source_file_family"] != FAMILY_FOR_CLASS[cls]:
            add("M_COVERAGE", f"{eid}: file family {x['source_file_family']!r} does not match class {cls}")
        cols_by_family.setdefault(x["source_file_family"], set()).add(x["source_column"])
        for key, bag in (
            ("entity_id", "entity"),
            ("sensor_external_id", "sensor"),
            ("mapping_id", "mapping"),
            ("reserved_id", "reserved"),
        ):
            v = x[key]
            if v is None:
                continue
            if v in seen[bag]:
                add("M_DUP", f"{key} {v!r} appears more than once (ambiguous)")
            seen[bag].add(v)
        ck = f"{x['source_file_family']}|{x['source_column']}"
        if ck in seen["column"]:
            add("M_DUP", f"column {ck!r} is mapped more than once (ambiguous)")
        seen["column"].add(ck)
        for v in (eid, x["sensor_external_id"], x["reserved_id"], x["asset_external_id"]):
            if v is not None:
                if not v.startswith(PREFIX) or v != v.lower():
                    add("M_ID", f"{v!r} must be lowercase and start with {PREFIX!r}")
                if DEMO_ID_RE.match(v):
                    add("M_ID", f"{v!r} collides with a demo id pattern")
        if x["mapping_id"] != PREFIX + "map." + eid[len(PREFIX) :]:
            add("M_MAPID", f"{eid}: mapping_id must be {PREFIX}map.<entity id without prefix>")
        if x["mapping_version"] != ver or x["mapping_status"] != "active":
            add("M_MAPID", f"{eid}: mapping_version must equal the file version and status must be active")
        if x["valid_time_status"] != "not_established" or x["applied_uniformly_over_window"] is not True:
            add("M_TIME", f"{eid}: valid_time_status not_established and applied_uniformly_over_window true (O-1)")
        if x["method"] not in MAPPING_METHODS or x["label_evidence"] not in LABEL_EVIDENCE:
            add("M_ENUM", f"{eid}: method / label_evidence")
        if x["label_evidence"] == "owner_verified":
            vref = x.get("verification_ref")
            if not vref:
                add("M_LABEL", f"{eid}: owner_verified requires a verification_ref (owner spot-check record)")
            else:
                _check_verification_ref(eid, vref, srcs, add)
        a = x["attribution"]
        if not (isinstance(a, dict) and set(a) == {"scope", "member_source_rack_ids", "split_allowed"}):
            add("M_ATTR", f"{eid}: attribution requires exactly scope, member_source_rack_ids, split_allowed")
            continue
        mem, scope = a["member_source_rack_ids"], a["scope"]
        if scope not in SCOPES or not isinstance(mem, list):
            add("M_ATTR", f"{eid}: scope or members invalid")
            continue
        if a["split_allowed"] is not False:
            add("M_GROUP_SPLIT", f"{eid}: split_allowed must be false")
        if (
            len(set(mem)) != len(mem)
            or mem != sorted(mem, key=lambda m: int(m) if str(m).isdigit() else 0)
            or not all(isinstance(m, str) and m in rack_ids for m in mem)
        ):
            add("M_ATTR", f"{eid}: members must be unique, ascending and existing racks")
        # evidence
        if x["mapping_state"] in ("mapped", "mapped_partial"):
            refs = x["evidence_refs"]
            if not (isinstance(refs, list) and refs):
                add("M_EVIDENCE", f"{eid}: a mapped entity needs at least one evidence reference")
            for ref in refs if isinstance(refs, list) else []:
                if not (
                    isinstance(ref, dict)
                    and set(ref) == {"source", "locator"}
                    and ref["source"] in srcs
                    and ref["locator"]
                ):
                    add("M_EVIDENCE", f"{eid}: evidence ref must be {{source, locator}} citing a known evidence source")
        if x["mapping_state"] == "unmapped" and (x["sensor_external_id"] is not None or x["load_in_v1"]):
            add("M_STATE", f"{eid}: an unmapped entity gets no sensor id and is never loaded")
        if (x["tier"] == "tier1") != (x["load_in_v1"] is True):
            add("M_STATE", f"{eid}: load_in_v1 is true exactly for tier1")
        if x["tier"] == "tier1" and x["mapping_state"] != "mapped":
            add("M_STATE", f"{eid}: every tier1 entity must be mapped")
        if x["mapping_state"] == "mapped_partial" and x["tier"] != "deferred":
            add("M_STATE", f"{eid}: mapped_partial is only for deferred entities")
        # words
        if x["source_position_word"] not in POSITION_WORDS[cls]:
            add("M_NAMING", f"{eid}: source_position_word {x['source_position_word']!r} not allowed for {cls}")
        if any(w in str(x["source_position_word"]).lower() for w in FORBIDDEN_WORDS):
            add("M_NAMING", f"{eid}: interpretation word in position word")
        # units
        m = x["measurand"]
        if cls in ("rack_probe", "cooling_unit_probe", "room_gradient_probe", "power_channel", "air_speed_channel"):
            exp_m = {"power_channel": "power", "air_speed_channel": "air_speed"}.get(cls, "temperature")
            if m != exp_m or x["unit"] != V5_UNITS[exp_m] or x["resolution_decimals"] != V5_DECIMALS[exp_m]:
                add(
                    "M_UNIT", f"{eid}: measurand/unit/resolution must be {exp_m}/{V5_UNITS[exp_m]}/{V5_DECIMALS[exp_m]}"
                )
            if (
                not (x["sensor_external_id"] and V5_SENSOR_RE.match(x["sensor_external_id"]))
                or x["sensor_external_id"] != eid
            ):
                add("M_ID", f"{eid}: sensor id must equal the entity id and match the contract sensor grammar")
            if not (x["asset_external_id"] and V5_ASSET_RE.match(x["asset_external_id"])):
                add("M_ID", f"{eid}: asset id {x['asset_external_id']!r} outside the contract asset grammar")
        else:
            if (
                m is not None
                or x["unit"] != "not_established"
                or x["sensor_external_id"] is not None
                or x["asset_external_id"] is not None
            ):
                add("M_UNIT", f"{eid}: deferred entity has no measurand, unit not_established, no sensor and no asset")
            if (
                x["reserved_id"]
                != f"{PREFIX}{'surround' if cls == 'surrounding_temperature' else 'ventilation'}.{normalise_header(x['source_column'])}"
            ):
                add("M_NORM", f"{eid}: reserved id must be prefix + normalised verbatim header")
        # class-specific attachment rules
        if cls == "rack_probe":
            lm = RACK_LABEL_RE.match(str(x["source_label"]))
            tm = TEMP_COL_RE.match(x["source_column"])
            if not lm or not tm:
                add("M_RACK", f"{eid}: rack probe needs a 'Rack N front|back ...' label and a Temperature header")
                continue
            rk = lm.group(1)
            probes_per_rack[rk] = probes_per_rack.get(rk, 0) + 1
            front_back[lm.group(2)] += 1
            if lm.group(2) != x["source_position_word"]:
                add("M_RACK", f"{eid}: position word differs from the label")
            if x["method"] != "source_image_label":
                add("M_RACK", f"{eid}: rack association comes from source_image_label")
            if (
                x["source_rack_id"] != rk
                or x["asset_external_id"] != f"{PREFIX}rack.{rk}"
                or x["target_asset_external_ids"] != [f"{PREFIX}rack.{rk}"]
            ):
                add("M_RACK", f"{eid}: probe must attach to exactly rack {rk}")
            if scope != "rack" or mem != [rk] or x["cardinality"] != "one_to_one":
                add("M_ATTR", f"{eid}: rack probe has scope rack, one member equal to its rack, one_to_one")
            if x["sensor_external_id"] != f"{PREFIX}temperature.mod{tm.group(1)}.ch{tm.group(2)}":
                add("M_ID", f"{eid}: sensor id must be built from the header only")
        elif cls in ("cooling_unit_probe", "room_gradient_probe", "air_speed_channel"):
            if (
                x["asset_external_id"] != PREFIX + "zone.serverroom"
                or scope != "room"
                or mem
                or x["source_rack_id"] is not None
            ):
                add("M_ROOM", f"{eid}: room-scope entity attaches to the room zone with no rack")
        elif cls == "power_channel":
            want = V5_POWER_MEMBERS.get(x["sensor_external_id"])
            if want is None:
                add("M_POWER", f"{eid}: unknown power channel")
                continue
            n = x["sensor_external_id"][-1]
            if x["asset_external_id"] != f"{PREFIX}pdu.ch{n}":
                add("M_POWER", f"{eid}: a power channel attaches to its own port asset, never to a rack")
            if (
                mem != want
                or scope != ("rack_group" if len(want) > 1 else "rack")
                or x["target_asset_external_ids"] != [f"{PREFIX}rack.{m_}" for m_ in want]
            ):
                add(
                    "M_POWER",
                    f"{eid}: members {want} with scope {'rack_group' if len(want) > 1 else 'rack'} are required; never split",
                )
            if len(want) > 1 and x["source_rack_id"] is not None:
                add("M_GROUP_SPLIT", f"{eid}: a group channel has no source_rack_id")
            if len(want) == 1 and x["source_rack_id"] != want[0]:
                add("M_POWER", f"{eid}: single-rack port needs source_rack_id {want[0]}")
            if (
                x["cardinality"] != ("many_to_one" if len(want) > 1 else "one_to_one")
                or x["method"] != "source_workbook_port_group"
            ):
                add("M_POWER", f"{eid}: cardinality / method (source_workbook_port_group)")
        else:  # deferred
            if scope != "unattributed" or mem or x["cardinality"] != "one_to_one":
                add("M_ATTR", f"{eid}: deferred entity is unattributed")
        if cls != "power_channel" and scope == "rack_group":
            add("M_GROUP_SPLIT", f"{eid}: only a power port may be group-attributed; temperature probes never are")

    # dataset-level expectations
    if class_counts != {k: v for k, v in EXPECTED["classes"].items() if k in class_counts} or set(class_counts) != set(
        EXPECTED["classes"]
    ):
        add("M_COUNT", f"class counts {dict(sorted(class_counts.items()))} != expected {EXPECTED['classes']}")
    if len(ents) != EXPECTED["total"]:
        add("M_COUNT", f"{len(ents)} entities, expected {EXPECTED['total']}")
    if probes_per_rack != EXPECTED["probes_per_rack"]:
        add("M_COUNT", f"rack probes per rack {probes_per_rack} != {EXPECTED['probes_per_rack']}")
    if (front_back["front"], front_back["back"]) != EXPECTED["front_back"]:
        add("M_COUNT", f"front/back {front_back} != {EXPECTED['front_back']}")
    cols = schema_columns if schema_columns is not None else _schema_columns()
    for fam, have in cols_by_family.items():
        want_cols = cols.get(fam, set())
        if have != want_cols:
            add(
                "M_COVERAGE",
                f"{fam}: unmapped columns {sorted(want_cols - have)}, unknown columns {sorted(have - want_cols)}",
            )
    for fam in set(cols) - set(cols_by_family):
        add("M_COVERAGE", f"{fam}: no entity maps any column of this file family")
    for it in doc["excluded_items"]:
        if not (isinstance(it, dict) and it.get("state") == "not_applicable" and it.get("reason")):
            add("M_STATE", "excluded items are not_applicable and carry a reason")
    return e
