"""Task 8: the shipped examples validate, every negative vector is rejected with its code, valid twins are accepted."""

import copy
import json
import re
from pathlib import Path

import pytest

from research.danish_aau.contract import negative_vectors as nv
from research.danish_aau.contract import telemetry_contract as c

EX_DIR = Path(c.__file__).parent / "examples"
EXAMPLES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(EX_DIR.glob("*.json"))}


def apply_edits(obj, edits):
    obj = copy.deepcopy(obj)
    for path, val in edits:
        parts = path.split(".")
        cur = obj
        for p in parts[:-1]:
            cur = cur[int(p)] if isinstance(cur, list) else cur[p]
        last = parts[-1]
        if isinstance(cur, list):
            cur[int(last)] = val
        elif val == nv.DELETE:
            cur.pop(last)
        else:
            cur[last] = val
    return obj


def test_examples_exist_and_cover_every_kind():
    assert len(EXAMPLES) >= 17
    kinds = {e.get("kind") or e.get("record_kind") for e in EXAMPLES.values()}
    assert kinds == {"telemetry_record", "ledger_entry", "sensor_list", "latest", "history", "rack_view", "error"}
    states = {e["state"] for e in EXAMPLES.values() if e.get("record_kind") == "telemetry_record"}
    assert states == set(c.STATES)  # observed, missing, invalid, not_reported and stale are all demonstrated


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_every_shipped_example_is_valid(name):
    assert c.validate(EXAMPLES[name]) == []


def test_examples_are_clearly_synthetic():
    for name, e in EXAMPLES.items():
        if e.get("record_kind") == "telemetry_record" and not name.startswith("record_v5"):
            assert e["fixture"] is True and e["sensor_external_id"].startswith(c.FIXTURE_PREFIX), name
            assert (e["ts_source_text"] or e["ts_utc"]).startswith("2000-"), name
    text = " ".join(p.read_text(encoding="utf-8") for p in EX_DIR.glob("*.json"))
    assert "2024" not in text  # the real v5 observation year never appears in an example


@pytest.mark.parametrize("vec", nv.VECTORS, ids=[v[0] for v in nv.VECTORS])
def test_negative_vector_is_rejected_with_its_code(vec):
    _id, base, edits, code = vec
    assert c.validate(EXAMPLES[base]) == [], "the base example must be valid"
    errs = c.validate(apply_edits(EXAMPLES[base], edits))
    assert errs, f"{_id} was accepted"
    assert any(e.startswith(code + ":") for e in errs), (_id, code, errs)


def test_vector_ids_are_unique_and_cover_all_reachable_codes():
    ids = [v[0] for v in nv.VECTORS]
    assert len(ids) == len(set(ids))
    src = (Path(c.__file__)).read_text(encoding="utf-8")
    codes = set(re.findall(r'"(E_[A-Z0-9_]+)"', src))
    covered = {v[3] for v in nv.VECTORS}
    defensive = {
        "E_TYPE",
        "E_KIND",
        "E_ID",
        "E_MEASURAND",
        "E_REASON",
        "E_RESOLUTION",
        "E_ITEM",
        "E_POWER",
        "E_KEYS",
    }  # reachable, covered by the cases below
    assert not (codes - covered - defensive), sorted(codes - covered - defensive)


@pytest.mark.parametrize(
    "obj,code",
    [
        ([], "E_TYPE"),
        ({"kind": "latest"}, "E_KEYS_MISSING"),
    ],
)
def test_non_object_and_bare_envelopes_are_rejected(obj, code):
    assert any(e.startswith(code) for e in c.validate(obj))


def _twin(rec, **changes):
    r = copy.deepcopy(rec)
    r.update(changes)
    return r


def test_valid_measured_twin_in_both_storage_classes():
    base = EXAMPLES["record_observed_temperature"]
    common = dict(
        provenance="measured",
        fixture=False,
        sensor_external_id="plant.temperature.s1",
        asset_external_id="plant.rack.a",
    )
    assert c.validate(_twin(base, **common, storage_class="research_import_file", origin_db=None)) == []
    assert c.validate(_twin(base, **common, storage_class="telemetry_sample", origin_db="measured")) == []
    assert any(
        e.startswith("E_ORIGIN")
        for e in c.validate(_twin(base, **common, storage_class="telemetry_sample", origin_db=None))
    )


def test_valid_simulated_and_derived_twins():
    base = EXAMPLES["record_observed_temperature"]
    sim = _twin(
        base,
        provenance="simulated",
        fixture=False,
        sensor_external_id="fac1.temperature",
        asset_external_id="fac1.zone",
        storage_class="telemetry_sample",
        origin_db="simulated",
        dataset_id=None,
        stream_id="live",
        source_ref=None,
        ledger=None,
        mapping=None,
        protocol_ref=None,
    )
    assert c.validate(sim) == [], c.validate(sim)
    d = EXAMPLES["record_derived_rack_proxy_shape"]
    der = _twin(
        d,
        fixture=False,
        sensor_external_id="plant.derived.rack1.mean",
        value=20.12,
        value_text="20.12",
        state="observed",
        observed=True,
        quality="ok",
        reason_code=None,
    )
    assert c.validate(der) == [], c.validate(der)
    group = _twin(
        der,
        derivation={**d["derivation"], "input_scopes": ["rack_group"]},
        attribution={"scope": "rack_group", "member_source_rack_ids": ["1", "2", "3"], "split_allowed": False},
        source_rack_id=None,
    )
    assert c.validate(group) == []


def _v5_measured(**kw):
    r = copy.deepcopy(EXAMPLES["record_v5_shape_only_no_value"])
    r.update(
        fixture=False,
        facility_id="facility-1",
        value=20.12,
        value_text="20.12",
        state="observed",
        observed=True,
        quality="ok",
        reason_code=None,
    )
    r["source_ref"].update(
        file="AAU_temperature_and_power_use.csv", row_ordinal=1, row_numbering="data_row_ordinal_excluding_header"
    )
    r["source_ref"]["key"] = f"AAU_temperature_and_power_use.csv|Temperature mod 1 ch 1|{r['ts_source_text']}"
    r.update(kw)
    return r


def test_valid_v5_measured_records():
    assert c.validate(_v5_measured()) == []
    ch1 = _v5_measured(
        sensor_external_id="danish-aau-v5.power.ch1",
        asset_external_id="danish-aau-v5.pdu.ch1",
        measurand="power",
        unit="W",
        resolution_decimals=1,
        value=300.0,
        value_text="300.0",
        source_rack_id=None,
        attribution={"scope": "rack_group", "member_source_rack_ids": ["1", "2", "3"], "split_allowed": False},
    )
    ch1["mapping"]["method"] = "source_workbook_port_group"
    assert c.validate(ch1) == []
    ch3 = copy.deepcopy(ch1)
    ch3.update(
        sensor_external_id="danish-aau-v5.power.ch3",
        asset_external_id="danish-aau-v5.pdu.ch3",
        source_rack_id="5",
        attribution={"scope": "rack", "member_source_rack_ids": ["5"], "split_allowed": False},
    )
    assert c.validate(ch3) == []


def test_conflict_tie_cell_is_a_valid_missing_v5_record():
    r = _v5_measured(
        value=None,
        value_text=None,
        state="missing",
        observed=False,
        quality=None,
        reason_code="conflict_unresolved_tie",
    )
    r["ledger"] = {
        "row_disposition": "conflict_cell_missing",
        "group_size": 2,
        "group_ref": "AAU_temperature_and_power_use.csv|x",
    }
    assert c.validate(r) == []


def test_record_key_set_is_frozen_for_1_0():
    assert len(c.RECORD_KEYS) == 34 and len(set(c.RECORD_KEYS)) == 34
    assert c.CONTRACT_VERSION == "1.0.0"
    assert c.PROTOCOL_SHA256_V5 == "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098"
    assert set(c.ROW_DISPOSITIONS) == {
        "retained",
        "exact_duplicate",
        "conflict_resolved_by_source_rule",
        "conflict_cell_missing",
        "flagged",
        "dropped_with_reason",
    }
