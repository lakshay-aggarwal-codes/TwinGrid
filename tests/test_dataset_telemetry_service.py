"""Task 16: the dataset telemetry service against the contract's reference validator. SYNTHETIC bundle only.

Runs without FastAPI: it exercises ``api.services.dataset_bundle_service`` directly and passes every envelope and record it
produces through ``research.danish_aau.contract.telemetry_contract.validate_envelope`` (tests may import ``research``;
production code may not).
"""

from __future__ import annotations

import ast
import calendar
import json
from pathlib import Path

import pytest

from api.services import dataset_bundle_service as svc
from research.danish_aau.contract import telemetry_contract as contract
from src.dataset_bundle import open_readonly
from src.dataset_bundle.loader import build_bundle
from tests.test_dataset_bundle import _panel

FAC, DS, STREAM = "fac-1", "danish-aau-v5", "import:danish-aau-v5"
T1, T2, POW1, POW3 = (
    "danish-aau-v5.temperature.mod1.ch1",
    "danish-aau-v5.temperature.mod1.ch2",
    "danish-aau-v5.power.ch1",
    "danish-aau-v5.power.ch3",
)
DERIVED = "derived.rack_power_total_1_6"


def ts(sec: int) -> str:
    return f"2000-01-01 {sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    out = tmp_path / "bundle" / "danish-aau-v5.sqlite"
    build_bundle(_panel(tmp_path), out)
    monkeypatch.setenv(svc.BUNDLE_ENV, str(out))
    monkeypatch.setenv(svc.FACILITY_ENV, FAC)
    conn = open_readonly(out)
    yield svc.make_ctx(conn, FAC, DS, STREAM)
    conn.close()


def valid(x):
    assert contract.validate_envelope(x) == [], contract.validate_envelope(x)
    return x


# ----------------------------------------------------------------------------------------------- contract conformance
def test_sensor_list_is_valid_and_lists_only_the_40_measured_channels(ctx):
    x = valid(svc.sensor_list(ctx, None, None))
    assert x["count"] == 40 and all(i["measurand_status"] == "sensor_present" for i in x["items"])
    assert not any(i["sensor_external_id"].startswith("derived.") for i in x["items"])
    assert {i["measurand"] for i in x["items"]} == {"temperature", "power"}
    assert valid(svc.sensor_list(ctx, "power", None))["count"] == 3


def test_group_power_never_appears_under_a_rack_filter(ctx):
    for rack, n in (("1", None), ("5", None)):
        items = svc.sensor_list(ctx, None, rack)["items"]
        ids = {i["sensor_external_id"] for i in items}
        assert POW1 not in ids and all(
            i["measurand"] == "temperature" for i in items if i["sensor_external_id"] != POW3
        )
    assert POW3 in {i["sensor_external_id"] for i in svc.sensor_list(ctx, None, "5")["items"]}


def test_latest_without_as_of_is_the_last_stored_second_and_valid(ctx):
    x = valid(svc.latest(ctx, T1, None, derived=False))
    assert x["record"]["ts_source_text"] == ts(19) and x["window_status"] == "inside_dataset_window"
    assert (
        x["record"]["provenance"] == "measured" and x["record"]["ts_utc"] is None and x["record_absent_reason"] is None
    )


def test_latest_at_a_second_returns_its_own_record_with_exact_text(ctx):
    x = valid(svc.latest(ctx, T1, ts(6), derived=False))
    r = x["record"]
    assert r["value_text"] == "21.30" and r["value"] == 21.3 and r["source_ref"]["row_ordinal"] == 7
    assert r["source_ref"]["column"] == "Temperature mod 1 ch 1" and r["ledger"]["row_disposition"] == "retained"


def test_a_tie_is_missing_with_reason_and_no_value(ctx):
    r = valid(svc.latest(ctx, T1, ts(10), derived=False))["record"]  # Temperature mod 2 ch 1 tie is another channel
    tie = valid(svc.latest(ctx, "danish-aau-v5.temperature.mod2.ch1", ts(10), derived=False))["record"]
    assert tie["state"] == "missing" and tie["value"] is None and tie["value_text"] is None and tie["observed"] is False
    assert (
        tie["reason_code"] == "conflict_unresolved_tie" and tie["ledger"]["row_disposition"] == "conflict_cell_missing"
    )
    assert tie["ledger"]["group_size"] == 2 and r["state"] == "observed"


def test_blank_cell_is_missing_with_blank_reason(ctx):
    r = valid(svc.latest(ctx, T2, ts(7), derived=False))["record"]
    assert (r["state"], r["reason_code"], r["value"]) == ("missing", "blank_cell", None)


def test_absent_second_answers_not_reported_or_outside_window_never_a_neighbour(ctx):
    inside = valid(svc.latest(ctx, T1, "2000-01-01 00:00:19", derived=False))
    assert inside["record"] is not None
    outside = valid(svc.latest(ctx, T1, "2000-01-01 05:00:00", derived=False))
    assert outside["record"] is None and outside["record_absent_reason"] == "outside_dataset_window"
    assert outside["window_status"] == "outside_dataset_window"
    before = valid(svc.latest(ctx, T1, "1999-12-31 23:59:59", derived=False))
    assert before["record_absent_reason"] == "outside_dataset_window"


def test_history_paging_is_strict_half_open_ascending_and_covers_every_record_once(ctx):
    seen, cursor = [], None
    while True:
        x = valid(
            svc.history(
                ctx,
                T1,
                derived=False,
                from_text=ts(2),
                to_text=ts(15),
                include_states=None,
                include_invalid=None,
                limit="4",
                cursor=cursor,
            )
        )
        seen += [r["ts_source_text"] for r in x["records"]]
        cursor = x["page"]["next_cursor"]
        if cursor is None:
            break
    assert seen == [ts(s) for s in range(2, 15)]  # to is exclusive, from inclusive, no gaps, no duplicates


def test_history_state_filter_and_missing_records_are_stored_records(ctx):
    x = valid(
        svc.history(
            ctx,
            "danish-aau-v5.temperature.mod2.ch1",
            derived=False,
            from_text=None,
            to_text=None,
            include_states="missing",
            include_invalid=None,
            limit=None,
            cursor=None,
        )
    )
    assert [r["ts_source_text"] for r in x["records"]] == [ts(10)] and x["include_states"] == ["missing"]
    none = valid(
        svc.history(
            ctx,
            T1,
            derived=False,
            from_text=None,
            to_text=None,
            include_states="invalid",
            include_invalid="true",
            limit=None,
            cursor=None,
        )
    )
    assert none["records"] == [] and none["include_invalid"] is True


def test_rack_view_group_power_is_a_pointer_and_rack_5_has_its_own_port(ctx):
    for rack in ("1", "2", "3", "4", "6"):
        x = valid(svc.rack_view(ctx, rack, None))
        p = x["power"]
        assert p["kind"] == "group_pointer" and p["value"] is None and p["split_allowed"] is False
        assert rack in p["member_source_rack_ids"] and len(p["member_source_rack_ids"]) >= 2
        assert "record" not in p and all(t["record"]["source_rack_id"] == rack for t in x["temperature_sensors"])
    x5 = valid(svc.rack_view(ctx, "5", ts(3)))
    assert x5["power"]["kind"] == "single_rack_port" and x5["power"]["record"]["source_rack_id"] == "5"


def test_no_cross_rack_broadcast_each_probe_belongs_to_exactly_one_rack(ctx):
    owner: dict[str, str] = {}
    for rack in "123456":
        for t in svc.rack_view(ctx, rack, None)["temperature_sensors"]:
            assert t["sensor_external_id"] not in owner
            owner[t["sensor_external_id"]] = rack
    assert len(owner) == 37
    for sid, rack in owner.items():
        assert svc.latest(ctx, sid, None, derived=False)["record"]["source_rack_id"] == rack


def test_derived_family_is_separate_and_valid(ctx):
    x = valid(svc.latest(ctx, DERIVED, ts(5), derived=True))
    r = x["record"]
    assert r["provenance"] == "derived" and r["storage_class"] == "derived_series" and r["unit"] == "W"
    assert r["attribution"]["scope"] == "rack_group" and r["attribution"]["member_source_rack_ids"] == list("123456")
    assert r["source_ref"] is None and r["derivation"]["formula_id"] == "F-POWER-SUM-1"
    ins = [svc.latest(ctx, f"danish-aau-v5.power.ch{i}", ts(5), derived=False)["record"] for i in (1, 2, 3)]
    assert round(r["value"], 1) == round(sum(i["value"] for i in ins), 1)
    gone = valid(svc.latest(ctx, DERIVED, ts(8), derived=True))["record"]  # a power channel is tied at second 8
    assert gone["state"] == "missing" and gone["value"] is None and gone["reason_code"] == "inputs_not_all_observed"
    h = valid(
        svc.history(
            ctx,
            DERIVED,
            derived=True,
            from_text=None,
            to_text=None,
            include_states=None,
            include_invalid=None,
            limit="1000",
            cursor=None,
        )
    )
    assert h["count"] == 20


def test_measured_and_derived_routes_never_serve_each_others_series(ctx):
    for fn in (
        lambda: svc.latest(ctx, DERIVED, None, derived=False),
        lambda: svc.latest(ctx, T1, None, derived=True),
        lambda: svc.history(
            ctx,
            DERIVED,
            derived=False,
            from_text=None,
            to_text=None,
            include_states=None,
            include_invalid=None,
            limit=None,
            cursor=None,
        ),
    ):
        with pytest.raises(svc.DatasetError) as e:
            fn()
        assert (e.value.status, e.value.code) == (404, "unknown_entity")


def test_registered_but_not_loaded_and_unknown_sensors_are_unknown_entity(ctx):
    tier2 = ctx.conn.execute(
        "SELECT external_id FROM entity WHERE kind = 'channel' AND load_in_v1 = 0 LIMIT 1"
    ).fetchone()[0]
    for sid in (tier2, "danish-aau-v5.temperature.mod9.ch9"):
        with pytest.raises(svc.DatasetError) as e:
            svc.latest(ctx, sid, None, derived=False)
        assert (e.value.status, e.value.code) == (404, "unknown_entity")
    with pytest.raises(svc.DatasetError) as e:
        svc.rack_view(ctx, "7", None)
    assert e.value.code == "unknown_entity"


@pytest.mark.parametrize(
    "kw",
    [
        {"from_text": "2000-01-01T00:00:01Z"},
        {"from_text": "2000-01-01 00:00:01+01:00"},
        {"to_text": "2000-13-01 00:00:00"},
        {"from_text": ts(5), "to_text": ts(5)},
        {"limit": "0"},
        {"limit": "1001"},
        {"limit": "ten"},
        {"cursor": "not-a-cursor"},
        {"include_states": "observed,bogus"},
        {"include_invalid": "maybe"},
    ],
)
def test_bad_history_parameters_are_bad_request_never_utc_guesses(ctx, kw):
    args = dict(from_text=None, to_text=None, include_states=None, include_invalid=None, limit=None, cursor=None) | kw
    with pytest.raises(svc.DatasetError) as e:
        svc.history(ctx, T1, derived=False, **args)
    assert (e.value.status, e.value.code) == (400, "bad_request")


def test_identity_checks_order_and_error_envelope(ctx):
    conn = ctx.conn
    cases = [
        ((None, DS, STREAM), (400, "bad_request")),
        ((FAC, DS, None), (400, "stream_required")),
        (("other", DS, STREAM), (404, "unknown_facility")),
        ((FAC, "nope", STREAM), (404, "unknown_dataset")),
        ((FAC, DS, "live"), (400, "bad_request")),
        ((FAC, DS, "import:other"), (400, "bad_request")),
    ]
    for (f, d, s), (status, code) in cases:
        with pytest.raises(svc.DatasetError) as e:
            svc.make_ctx(conn, f, d, s)
        assert (e.value.status, e.value.code) == (status, code)
        env = svc.error_envelope(e.value, f, d, s)
        assert contract.validate_envelope(env) == [] and set(env) == {
            "contract_version", "kind", "status", "code", "message", "facility_id", "dataset_id", "stream_id"}  # fmt: skip


def test_dataset_record_carries_attribution_and_no_server_paths(ctx):
    d = svc.dataset_record(ctx)
    assert d["licence"] == "CC BY 4.0" and d["attribution_text"] and d["modifications_statement"]
    assert d["data_status"] == "historical_import_not_live" and d["measured_series_count"] == 40
    assert d["derived_series"][0]["split_per_rack"] is False and len(d["racks"]) == 6
    assert d["window"]["first_source_text"] == ts(0)
    assert str(Path(svc.configured_path()).parent) not in json.dumps(d)


def test_time_parsing_is_naive_label_seconds_like_the_loader(ctx):
    assert svc.parse_source_text("t", ts(7)) == calendar.timegm((2000, 1, 1, 0, 0, 7))
    row = ctx.conn.execute("SELECT t_naive_s FROM second WHERE ts_text = ?", (ts(7),)).fetchone()
    assert row[0] == svc.parse_source_text("t", ts(7))


def test_contract_version_matches_the_reference_validator():
    assert svc.CONTRACT_VERSION == contract.CONTRACT_VERSION


def test_service_is_read_only_and_never_imports_research():
    tree = ast.parse(Path(svc.__file__).read_text(encoding="utf-8"))
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any(m.split(".")[0] == "research" for m in mods)
    text = Path(svc.__file__).read_text(encoding="utf-8").upper()
    for word in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE TABLE"):
        assert word not in text.replace("DERIVED_OBSERVATION", "")


def test_bundle_unavailable_without_both_settings(tmp_path, monkeypatch, ctx):
    assert svc.bundle_available()
    monkeypatch.delenv(svc.FACILITY_ENV)
    assert not svc.bundle_available()
    monkeypatch.setenv(svc.FACILITY_ENV, FAC)
    monkeypatch.setenv(svc.BUNDLE_ENV, str(tmp_path / "missing.sqlite"))
    assert not svc.bundle_available()
