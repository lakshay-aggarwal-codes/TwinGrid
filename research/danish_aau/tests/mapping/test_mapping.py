"""Task 13 tests: identity mapping, its negative controls, contract compatibility and the derivation guard.

Synthetic only: record values are patterned test numbers with year-2000 timestamps held in memory. Nothing reads or
writes real data.
"""

from __future__ import annotations

import copy
import json
import re
import tempfile
from pathlib import Path

import pytest

from research.danish_aau.adapter.schema import FILE_SPECS
from research.danish_aau.contract import telemetry_contract as tc
from research.danish_aau.mapping import (
    DerivationNotApproved,
    MappingValidationError,
    UnmappedEntityError,
    attribution_block,
    load_derivation_registry,
    load_mapping,
    mapping_block,
    rack_measurand_status,
    rack_view_parts,
    require_approved,
    sensor_list_items,
    validate_derivation_definition,
    validate_mapping,
)
from research.danish_aau.mapping import __main__ as cli
from research.danish_aau.mapping.errors import AmbiguousMappingError
from research.danish_aau.mapping.loader import MAPPING_PATH, build_registry, mapping_file_sha256
from research.danish_aau.mapping.report import build_report

REPO = Path(__file__).resolve().parents[4]
P = "danish-aau-v5."
DOC = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
REG = load_mapping()


def _doc():
    return copy.deepcopy(DOC)


def _ent(doc, entity_id):
    return next(e for e in doc["entities"] if e["entity_id"] == entity_id)


def _codes(errors):
    return {e.split(":")[0] for e in errors}


# ---------------------------------------------------------------- the committed mapping


def test_committed_mapping_is_valid_and_counts_are_exact():
    assert validate_mapping(DOC) == []
    c = REG.counts()
    assert c["entities"] == 79 and c["unmapped"] == 0 and c["tier1_unmapped"] == 0
    assert c["by_class"] == {
        "air_speed_channel": 16, "cooling_unit_probe": 6, "power_channel": 3, "rack_probe": 37,
        "room_gradient_probe": 5, "surrounding_temperature": 6, "ventilation": 6,
    }  # fmt: skip
    assert c["by_mapping_state"] == {"mapped": 67, "mapped_partial": 12}
    assert len(DOC["racks"]) == 6 and len(DOC["power_ports"]) == 3


def test_file_is_lf_only_without_bom_and_hash_is_stable():
    raw = MAPPING_PATH.read_bytes()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    assert mapping_file_sha256() == mapping_file_sha256() == REG.sha256
    assert DOC["mapping_file"]["status"] == "ready_for_review" and DOC["mapping_file"]["decided_by"] is None


def test_every_mapped_entity_has_evidence_and_a_stable_id():
    for e in DOC["entities"]:
        assert e["evidence_refs"], e["entity_id"]
        for ref in e["evidence_refs"]:
            assert ref["source"] in DOC["evidence_sources"] and ref["locator"]
        assert e["mapping_id"] == P + "map." + e["entity_id"][len(P) :]
        assert e["mapping_version"] == 1 and e["valid_time_status"] == "not_established"
    sensors = [e["sensor_external_id"] for e in DOC["entities"] if e["sensor_external_id"]]
    assert len(sensors) == len(set(sensors)) == 67
    assert all(tc.V5_SENSOR_RE.match(s) for s in sensors)
    assets = {e["asset_external_id"] for e in DOC["entities"] if e["asset_external_id"]}
    assert all(tc.V5_ASSET_RE.match(a) for a in assets)
    assert not any(re.match(r"^(zone-\d+|facility-level|fac\d+\.)", s) for s in sensors)


def test_ids_are_built_from_the_header_only():
    for e in DOC["entities"]:
        m = re.match(r"^Temperature mod (\d+) ch (\d+)$", e["source_column"])
        if m:
            assert e["sensor_external_id"] == f"{P}temperature.mod{m.group(1)}.ch{m.group(2)}"
            assert "rack" not in e["sensor_external_id"] and "front" not in e["sensor_external_id"]
        if e["source_entity_class"] == "air_speed_channel":
            assert e["sensor_external_id"] == P + "velocity." + e["source_column"].split()[1]


def test_all_79_adapter_columns_are_mapped_exactly_once():
    fam: dict[str, set[str]] = {}
    for s in FILE_SPECS:
        fam.setdefault(s.family, set()).update(s.measurement_columns)
    assert {k: len(v) for k, v in fam.items()} == {
        "temperature_power": 51, "air_speed": 16, "surrounding_temperatures": 6, "ventilation": 6,
    }  # fmt: skip
    keys = [(e["source_file_family"], e["source_column"]) for e in DOC["entities"]]
    assert len(keys) == len(set(keys)) == 79
    for f, cols in fam.items():
        assert {c for ff, c in keys if ff == f} == cols


def test_rack_probe_attachment_counts():
    per: dict[str, list[str]] = {}
    for e in REG.entities(load_in_v1=True):
        if e["source_entity_class"] == "rack_probe":
            per.setdefault(e["source_rack_id"], []).append(e["source_position_word"])
    assert {k: len(v) for k, v in sorted(per.items())} == {"1": 3, "2": 3, "3": 3, "4": 3, "5": 22, "6": 3}
    assert per["5"].count("front") == 4 and per["5"].count("back") == 18
    assert sum(v.count("front") for v in per.values()) == 9 and sum(v.count("back") for v in per.values()) == 28
    # spot checks of individually distinguishable identities
    assert REG.sensor(P + "temperature.mod1.ch1")["source_rack_id"] == "2"
    assert REG.sensor(P + "temperature.mod5.ch4")["source_label"] == "Rack 4 back 1"
    assert REG.sensor(P + "temperature.mod4.ch3")["attribution"]["scope"] == "room"
    assert REG.sensor(P + "temperature.mod3.ch1")["source_entity_class"] == "cooling_unit_probe"


def test_power_groups_are_never_split():
    p1, p2, p3 = (REG.sensor(P + f"power.ch{n}") for n in (1, 2, 3))
    assert p1["attribution"] == {
        "scope": "rack_group",
        "member_source_rack_ids": ["1", "2", "3"],
        "split_allowed": False,
    }
    assert p2["attribution"] == {"scope": "rack_group", "member_source_rack_ids": ["4", "6"], "split_allowed": False}
    assert p3["attribution"] == {"scope": "rack", "member_source_rack_ids": ["5"], "split_allowed": False}
    assert p1["source_rack_id"] is None and p2["source_rack_id"] is None and p3["source_rack_id"] == "5"
    assert [p1["asset_external_id"], p2["asset_external_id"], p3["asset_external_id"]] == [
        P + f"pdu.ch{n}" for n in (1, 2, 3)
    ]
    assert p1["source_label"] == "Rack 1-3" and p2["source_label"] == "Rack 4+6"
    assert not any(
        e["measurand"] == "power" and e["asset_external_id"].startswith(P + "rack.") for e in DOC["entities"]
    )


def test_no_server_no_inlet_outlet_words_and_time_not_established():
    assert DOC["site"] == {"site_status": "location_not_established", "server_status": "not_present_in_source"}
    assert not any("server" in e["source_entity_class"] for e in DOC["entities"])
    words = {e["source_position_word"] for e in DOC["entities"]}
    assert words == {
        "front",
        "back",
        "cooling unit",
        "room",
        "power measurement port",
        "room boundary",
        "ahu or damper",
    }
    assert not any(w in " ".join(words) for w in ("inlet", "outlet", "supply", "return"))
    assert all(e["applied_uniformly_over_window"] is True for e in DOC["entities"])


def test_tier_and_load_flags():
    t1 = REG.entities(tier="tier1")
    assert len(t1) == 40 and all(e["load_in_v1"] for e in t1)
    assert len(REG.entities(tier="tier2")) == 27 and not any(e["load_in_v1"] for e in REG.entities(tier="tier2"))
    d = REG.entities(tier="deferred")
    assert len(d) == 12 and all(e["sensor_external_id"] is None and e["unit"] == "not_established" for e in d)
    assert len({e["reserved_id"] for e in d}) == 12


def test_matches_task7_appendix_a_when_the_adr_is_present():
    adr = REPO / "reports" / "telemetry_handoff" / "task07" / "TASK_07_ADR.md"
    if not adr.exists():
        pytest.skip("TASK_07_ADR.md not present in this checkout")
    text = adr.read_text(encoding="utf-8").replace("\r", "")
    n = 0
    for line in text.splitlines():
        if line.startswith("| `Temperature"):
            c = [x.strip() for x in line.strip("|").split("|")]
            e = REG.sensor(c[1].strip("`"))
            assert e["source_column"] == c[0].strip("`") and e["source_label"] == c[2]
            assert e["source_position_word"] == c[4] and e["source_entity_class"] == c[5]
            assert f"`{e['asset_external_id']}`" in c[6]
            n += 1
    assert n == 48
    assert hashlib_lf(adr) == DOC["mapping_file"]["task7_adr_sha256_lf_normalised"]


def hashlib_lf(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes().replace(b"\r", b"")).hexdigest()


# ---------------------------------------------------------------- negative controls (each must be rejected)


def _expect(mutator, code):
    d = _doc()
    mutator(d)
    errs = validate_mapping(d)
    assert code in _codes(errs), (code, errs[:3])
    with pytest.raises(MappingValidationError):
        load_mapping(doc=d)


def test_rejects_split_allowed_true():
    _expect(lambda d: _ent(d, P + "power.ch1")["attribution"].update(split_allowed=True), "M_GROUP_SPLIT")


def test_rejects_group_channel_with_a_source_rack():
    _expect(lambda d: _ent(d, P + "power.ch1").update(source_rack_id="1"), "M_GROUP_SPLIT")


def test_rejects_group_attributed_temperature_probe():
    def m(d):
        a = _ent(d, P + "temperature.mod1.ch1")["attribution"]
        a.update(scope="rack_group", member_source_rack_ids=["2", "3"])

    _expect(m, "M_GROUP_SPLIT")


def test_rejects_power_channel_attached_to_a_rack():
    _expect(lambda d: _ent(d, P + "power.ch1").update(asset_external_id=P + "rack.1"), "M_POWER")


def test_rejects_changed_power_membership():
    _expect(lambda d: _ent(d, P + "power.ch2")["attribution"].update(member_source_rack_ids=["4", "5", "6"]), "M_POWER")


def test_rejects_missing_evidence():
    _expect(lambda d: _ent(d, P + "temperature.mod2.ch8").update(evidence_refs=[]), "M_EVIDENCE")


def test_rejects_evidence_citing_an_unknown_source():
    _expect(
        lambda d: _ent(d, P + "temperature.mod2.ch8")["evidence_refs"].append({"source": "nowhere", "locator": "x"}),
        "M_EVIDENCE",
    )


def test_rejects_ambiguous_duplicate_column():
    def m(d):
        d["entities"].append(copy.deepcopy(_ent(d, P + "temperature.mod1.ch1")))

    _expect(m, "M_DUP")


def test_rejects_unmapped_source_column():
    def m(d):
        d["entities"] = [e for e in d["entities"] if e["entity_id"] != P + "temperature.mod8.ch4"]

    errs = validate_mapping(_after(m))
    assert {"M_COVERAGE", "M_COUNT"} <= _codes(errs)


def _after(mutator):
    d = _doc()
    mutator(d)
    return d


def test_rejects_unknown_extra_column():
    def m(d):
        x = copy.deepcopy(_ent(d, P + "velocity.16"))
        x.update(
            entity_id=P + "velocity.17",
            sensor_external_id=P + "velocity.17",
            source_column="velocity 17",
            mapping_id=P + "map.velocity.17",
        )
        d["entities"].append(x)

    assert {"M_COVERAGE", "M_COUNT"} <= _codes(validate_mapping(_after(m)))


def test_rejects_probe_attached_to_the_wrong_rack():
    _expect(
        lambda d: _ent(d, P + "temperature.mod1.ch1").update(
            asset_external_id=P + "rack.3", target_asset_external_ids=[P + "rack.3"]
        ),
        "M_RACK",
    )


def test_rejects_probe_with_two_target_racks():
    _expect(
        lambda d: _ent(d, P + "temperature.mod1.ch1").update(target_asset_external_ids=[P + "rack.2", P + "rack.3"]),
        "M_RACK",
    )


def test_rejects_invented_inlet_outlet_word():
    _expect(lambda d: _ent(d, P + "temperature.mod1.ch1").update(source_position_word="inlet"), "M_NAMING")
    _expect(lambda d: d["racks"][0].update(name="Rack 1 supply side"), "M_NAMING")


def test_rejects_claimed_time_validity():
    _expect(lambda d: _ent(d, P + "temperature.mod1.ch1").update(valid_time_status="established"), "M_TIME")
    _expect(lambda d: d["time"].update(valid_time_status="source_documented"), "M_TIME")


def test_rejects_demo_colliding_or_foreign_ids():
    _expect(lambda d: _ent(d, P + "temperature.mod1.ch1").update(sensor_external_id="fac1.temperature"), "M_ID")
    _expect(
        lambda d: _ent(d, P + "temperature.mod1.ch1").update(sensor_external_id=P + "temperature.mod1.ch1.r2"), "M_ID"
    )


def test_rejects_owner_verified_without_a_record():
    _expect(lambda d: _ent(d, P + "temperature.mod1.ch1").update(label_evidence="owner_verified"), "M_LABEL")


def test_rejects_server_entities_and_unknown_classes():
    _expect(lambda d: _ent(d, P + "temperature.mod1.ch1").update(source_entity_class="server_probe"), "M_ENUM")


def test_rejects_wrong_protocol_hash_and_unapproved_decision_trail():
    _expect(lambda d: d["mapping_file"].update(protocol_sha256="0" * 64), "M_PROTOCOL")
    _expect(lambda d: d["mapping_file"].update(status="approved"), "M_STATUS")


def test_rejects_unmapped_entity_that_keeps_a_sensor_or_is_loaded():
    _expect(lambda d: _ent(d, P + "velocity.1").update(mapping_state="unmapped"), "M_STATE")
    _expect(lambda d: _ent(d, P + "velocity.1").update(load_in_v1=True), "M_STATE")
    _expect(
        lambda d: _ent(d, P + "temperature.mod1.ch1").update(
            mapping_state="unmapped", sensor_external_id=P + "temperature.mod1.ch1"
        ),
        "M_STATE",
    )


def test_rejects_stale_mapping_version_and_bad_reserved_id():
    _expect(lambda d: _ent(d, P + "velocity.1").update(mapping_version=2), "M_MAPID")
    _expect(
        lambda d: _ent(d, P + "surround.outdoor-temperature").update(reserved_id=P + "surround.outdoor_temperature"),
        "M_NORM",
    )


def test_rejects_wrong_units_or_resolution():
    _expect(lambda d: _ent(d, P + "power.ch1").update(unit="kW"), "M_UNIT")
    _expect(lambda d: _ent(d, P + "temperature.mod1.ch1").update(resolution_decimals=1), "M_UNIT")


def test_registry_refuses_ambiguity_and_unknown_lookups():
    d = _doc()
    d["entities"].append(copy.deepcopy(d["entities"][0]))
    with pytest.raises(AmbiguousMappingError):
        build_registry(d, "x")
    with pytest.raises(UnmappedEntityError):
        REG.for_column("temperature_power", "Temperature mod 9 ch 1")
    with pytest.raises(UnmappedEntityError):
        REG.sensor(P + "temperature.mod9.ch9")
    assert REG.for_column("temperature_power", "Power Ch 1 (W)")["sensor_external_id"] == P + "power.ch1"


# ---------------------------------------------------------------- contract compatibility


def _record(sensor_id: str):
    base = json.loads(
        (REPO / "research/danish_aau/contract/examples/record_v5_shape_only_no_value.json").read_text(encoding="utf-8")
    )
    e = REG.sensor(sensor_id)
    r = copy.deepcopy(base)
    r.update(
        state="observed", observed=True, value=20.12 if e["measurand"] == "temperature" else 100.0,
        value_text="20.12" if e["measurand"] == "temperature" else "100.0", quality="ok", reason_code=None,
        fixture=False, facility_id="1", sensor_external_id=sensor_id, asset_external_id=e["asset_external_id"],
        measurand=e["measurand"], unit=e["unit"], resolution_decimals=e["resolution_decimals"],
        source_rack_id=e["source_rack_id"], mapping=mapping_block(sensor_id), attribution=attribution_block(sensor_id),
        ts_source_text="2000-01-01 00:00:01",
    )  # fmt: skip
    r["source_ref"] = dict(
        base["source_ref"],
        file="AAU_temperature_and_power_use.csv",
        column=e["source_column"],
        ts_text="2000-01-01 00:00:01",
        row_ordinal=1,
        key=f"AAU_temperature_and_power_use.csv|{e['source_column']}|2000-01-01 00:00:01",
    )
    r["ledger"] = dict(base["ledger"], group_ref="AAU_temperature_and_power_use.csv|2000-01-01 00:00:01")
    return r


def test_mapping_blocks_have_the_exact_contract_keys_and_records_validate():
    for sid in (
        P + "temperature.mod1.ch1",
        P + "temperature.mod2.ch1",
        P + "power.ch1",
        P + "power.ch2",
        P + "power.ch3",
    ):
        assert set(mapping_block(sid)) == {
            "mapping_id",
            "mapping_version",
            "method",
            "label_evidence",
            "valid_time_status",
            "applied_uniformly_over_window",
        }
        assert tc.validate_record(_record(sid)) == [], sid


def test_contract_rejects_a_split_of_a_mapped_group_channel():
    r = _record(P + "power.ch1")
    r["attribution"] = {"scope": "rack", "member_source_rack_ids": ["1"], "split_allowed": False}
    r["source_rack_id"] = "1"
    assert tc.validate_record(r)
    r2 = _record(P + "power.ch1")
    r2["attribution"]["split_allowed"] = True
    assert tc.validate_record(r2)


def test_attribution_block_is_a_copy():
    a = attribution_block(P + "power.ch1")
    a["member_source_rack_ids"].append("9")
    assert REG.sensor(P + "power.ch1")["attribution"]["member_source_rack_ids"] == ["1", "2", "3"]


def test_sensor_list_envelope_is_valid_and_has_only_tier1():
    items = sensor_list_items()
    assert len(items) == 40 and not any("zone.serverroom" in i["asset_external_id"] for i in items)
    env = {
        "contract_version": "1.0.0", "kind": "sensor_list", "facility_id": "1", "dataset_id": "danish-aau-v5",
        "stream_id": "import:danish-aau-v5", "count": len(items), "items": items,
    }  # fmt: skip
    assert tc.validate_envelope(env) == []
    assert len(sensor_list_items(load_in_v1_only=False)) == 67


def test_rack_measurand_status_and_rack_view_identity_halves():
    for rack, sid, status in (
        ("1", "power.ch1", "group_channel_only"),
        ("2", "power.ch1", "group_channel_only"),
        ("3", "power.ch1", "group_channel_only"),
        ("4", "power.ch2", "group_channel_only"),
        ("6", "power.ch2", "group_channel_only"),
        ("5", "power.ch3", "sensor_present"),
    ):
        assert rack_measurand_status(rack, "power") == (status, [P + sid])
    assert rack_measurand_status("1", "air_speed") == ("no_sensor_for_asset", [])
    assert (
        rack_measurand_status("5", "temperature")[0] == "sensor_present"
        and len(rack_measurand_status("5", "temperature")[1]) == 22
    )
    with pytest.raises(UnmappedEntityError):
        rack_measurand_status("7", "power")
    for rack in "123456":
        v = rack_view_parts(rack)
        env = {
            "contract_version": "1.0.0", "kind": "rack_view", "facility_id": "1", "dataset_id": "danish-aau-v5",
            "stream_id": "import:danish-aau-v5", "source_rack_id": rack, "asset_external_id": v["asset_external_id"],
            "temperature_sensors": [dict(t, record=None) for t in v["temperature_sensors"]],
            "power": v["power"] if v["power"]["kind"] != "single_rack_port" else {"kind": "not_available", "reason": "record supplied by the serving layer"},
        }  # fmt: skip
        assert tc.validate_envelope(env) == [], (rack, tc.validate_envelope(env))
    assert rack_view_parts("2")["power"]["value"] is None and rack_view_parts("2")["power"][
        "member_source_rack_ids"
    ] == ["1", "2", "3"]


# ---------------------------------------------------------------- derivations


def _defn(**kw):
    d = {
        "derived_name": "derived.room_power_total", "provenance": "derived", "operation": "sum",
        "inputs": [P + "power.ch1", P + "power.ch2", P + "power.ch3"], "output_measurand": "power", "output_unit": "W",
        "output_scope": "rack_group", "output_member_source_rack_ids": ["1", "2", "3", "4", "5", "6"],
        "formula_id": "F-TEST", "formula_text": "sum of the three measured power channels", "code_version": "test",
        "mapping_version": 1, "method_approval_ref": "TEST-ONLY", "approved_on": "2000-01-01",
    }  # fmt: skip
    d.update(kw)
    return d


def test_only_the_owner_approved_derivation_exists():
    reg = load_derivation_registry()
    assert [d["derived_name"] for d in reg["approved"]] == ["derived.rack_power_total_1_6"]
    d = require_approved("derived.rack_power_total_1_6")
    assert d["inputs"] == [P + "power.ch1", P + "power.ch2", P + "power.ch3"]
    assert (
        d["operation"] == "sum"
        and d["output_scope"] == "rack_group"
        and d["output_member_source_rack_ids"] == ["1", "2", "3", "4", "5", "6"]
    )
    assert "2026-11-06" in d["method_approval_ref"] and d["approved_on"] == "2026-11-06"
    assert "never a partial sum" in d["formula_text"] and "never divided per rack" in d["formula_text"]
    assert validate_derivation_definition(d, REG) == []
    # everything else stays refused
    for name in (
        "derived.rack_temperature_mean",
        "derived.rack1_power",
        "derived.rack_power_split",
        "derived.room_power_total",
        "derived.power.ch1",
    ):
        with pytest.raises(DerivationNotApproved):
            require_approved(name)


def test_contract_1_1_carries_the_approved_derived_v5_power_total():
    """Contract 1.1.0 added the derived v5 id grammar; the approved power total is a valid derived record."""
    base = json.loads(
        (REPO / "research/danish_aau/contract/examples/record_derived_rack_proxy_shape.json").read_text(
            encoding="utf-8"
        )
    )
    d = require_approved("derived.rack_power_total_1_6")
    r = copy.deepcopy(base)
    r.update(
        dataset_id="danish-aau-v5", stream_id="import:danish-aau-v5", facility_id="1", fixture=False, provenance="derived",
        storage_class="derived_series", origin_db=None, measurand="power", unit="W", resolution_decimals=1, state="observed",
        observed=True, value=300.0, value_text="300.0", quality="ok", reason_code=None, source_rack_id=None,
        attribution={"scope": "rack_group", "member_source_rack_ids": d["output_member_source_rack_ids"], "split_allowed": False},
        asset_external_id=P + "zone.serverroom", sensor_external_id=d["derived_name"],
        protocol_ref={"protocol_sha256": tc.PROTOCOL_SHA256_V5},
        derivation={
            "formula_id": d["formula_id"], "formula_text": d["formula_text"],
            "inputs": [{"sensor_external_id": s, "source_ref_key": f"f.csv|{s}|2000-01-01 00:00:01"} for s in d["inputs"]],
            "input_scopes": ["rack_group", "rack_group", "rack"], "mapping_id": P + "map.power.ch1",
            "mapping_version": 1, "code_version": d["code_version"], "method_approval_ref": d["method_approval_ref"],
        },
    )  # fmt: skip
    assert tc.validate_record(r) == []


def test_derivation_rules_accept_only_additive_measured_power_with_lineage():
    assert validate_derivation_definition(_defn(), REG) == []  # shape only; approval is the owner's
    assert (
        validate_derivation_definition(
            _defn(inputs=[P + "power.ch1", P + "power.ch3"], output_member_source_rack_ids=["1", "2", "3", "5"]), REG
        )
        == []
    )


def test_derivation_rejects_temperature_sum_group_split_and_missing_lineage():
    t = [P + "temperature.mod1.ch1", P + "temperature.mod2.ch7"]
    assert "D_TEMP_SUM" in _codes(
        validate_derivation_definition(
            _defn(
                inputs=t,
                output_measurand="temperature",
                output_unit="degC",
                output_scope="rack",
                output_member_source_rack_ids=["2"],
            ),
            REG,
        )
    )
    assert "D_GROUP_SPLIT" in _codes(
        validate_derivation_definition(
            _defn(operation="equal_split", inputs=[P + "power.ch1"], output_member_source_rack_ids=["1", "2", "3"]), REG
        )
    )
    assert "D_GROUP_SPLIT" in _codes(
        validate_derivation_definition(
            _defn(inputs=[P + "power.ch1"], operation="mean", output_scope="rack", output_member_source_rack_ids=["1"]),
            REG,
        )
    )
    assert "D_MIX" in _codes(
        validate_derivation_definition(_defn(inputs=[P + "power.ch1", P + "temperature.mod1.ch1"]), REG)
    )
    assert "D_APPROVAL" in _codes(validate_derivation_definition(_defn(method_approval_ref=""), REG))
    assert "D_LINEAGE" in _codes(validate_derivation_definition(_defn(formula_text=""), REG))
    assert "D_NAME" in _codes(validate_derivation_definition(_defn(derived_name=P + "power.ch1"), REG))
    assert "D_PROVENANCE" in _codes(validate_derivation_definition(_defn(provenance="measured"), REG))
    assert "D_INPUT" in _codes(validate_derivation_definition(_defn(inputs=[P + "velocity.1"]), REG))
    assert "D_INPUT" in _codes(validate_derivation_definition(_defn(inputs=[P + "power.ch1", P + "power.ch1"]), REG))
    assert "D_POWER_ADD" in _codes(
        validate_derivation_definition(_defn(output_member_source_rack_ids=["1", "2", "3"]), REG)
    )
    assert "D_KEYS" in _codes(validate_derivation_definition({"derived_name": "derived.x"}, REG))


def test_registry_accepts_an_owner_approved_entry_and_rejects_a_bad_one():
    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "g.json"
        good.write_text(json.dumps({"registry_version": 1, "approved": [_defn()]}), encoding="utf-8")
        assert require_approved("derived.room_power_total", good)["provenance"] == "derived"
        with pytest.raises(DerivationNotApproved):
            require_approved("derived.other", good)
        bad = Path(td) / "b.json"
        bad.write_text(
            json.dumps({"registry_version": 1, "approved": [_defn(operation="equal_split", inputs=[P + "power.ch1"])]}),
            encoding="utf-8",
        )
        with pytest.raises(MappingValidationError):
            load_derivation_registry(bad)


# ---------------------------------------------------------------- report and hygiene


def test_report_is_aggregate_and_counts_unmapped():
    r = build_report(REG)
    assert r["counts"]["unmapped"] == 0 and r["unmapped_entities"] == [] and len(r["deferred_entities"]) == 12
    assert r["label_evidence"] == {"agent_transcribed": 64, "not_applicable": 12, "source_document": 3}
    assert r["derivations_approved"] == 1 and r["derivations_approved_ids"] == ["derived.rack_power_total_1_6"]
    assert r["mapping_status"] == "ready_for_review"
    assert not re.search(r"\d+\.\d+\s*(degC|W)\b", json.dumps(r))


def test_cli_verify_and_report():
    assert cli.main(["verify"]) == 0
    assert cli.main(["report"]) == 0


def test_mapping_package_reads_no_data():
    src = "\n".join(p.read_text(encoding="utf-8") for p in Path(MAPPING_PATH).parent.glob("*.py"))
    assert not re.search(
        r"read_csv|realData|open_raw_bytes|AauCsvReader|telemetry_sample|sqlite3",
        src.replace("telemetry_sample table", ""),
    )
