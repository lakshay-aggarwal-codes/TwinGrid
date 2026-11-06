"""Registry expectations, column classification (no guessing), and raw-data immutability."""

import os

import pytest
import synthetic_fixtures as fx

from research.danish_aau.evaluation.guard import (
    RawDataGuard,
    RawDataModified,
    diff_snapshots,
    open_raw_bytes,
    snapshot,
)
from research.danish_aau.evaluation.provenance import Provenance, UnitBasis
from research.danish_aau.evaluation.registry import DEFAULT_REGISTRY, classify_column, registry_sha256


def test_registry_carries_the_numbers_reported_in_the_context_document():
    by_key = {e.key: e for e in DEFAULT_REGISTRY}
    t = by_key["temperature_power_25"]
    assert (t.expected_size_bytes, t.expected_n_columns, t.expected_rows) == (46_786_437, 52, 90_902)
    assert by_key["air_speed_25"].expected_n_columns == 17 and by_key["air_speed_25"].expected_rows == 9_091
    assert by_key["surrounding_temperatures"].expected_rows == 1_526
    assert by_key["ventilation"].expected_rows == 4_576
    assert all(e.to_dict()["expectation_source"] == "context_doc_reported_unverified" for e in DEFAULT_REGISTRY)


def test_registry_hash_is_stable():
    assert registry_sha256() == registry_sha256() and len(registry_sha256()) == 64


def test_power_columns_are_measured_watts_from_the_header():
    spec = classify_column("temperature_power_25", "Power Ch 2 (W)")
    assert (spec.kind, spec.provenance, spec.unit, spec.unit_basis) == (
        "power",
        Provenance.MEASURED,
        "W",
        UnitBasis.CSV_HEADER,
    )
    assert "unresolved" in spec.note


def test_temperature_and_velocity_units_are_paper_context_not_header():
    t = classify_column("temperature_power_25", "Temperature mod 3 ch 5")
    v = classify_column("air_speed_25", "velocity 16")
    assert (t.unit, t.unit_basis) == ("degC", UnitBasis.PAPER_CONTEXT)
    assert (v.unit, v.unit_basis) == ("m/s", UnitBasis.PAPER_CONTEXT)


@pytest.mark.parametrize("column", fx.VENTILATION_HEADER[1:])
def test_ventilation_units_are_never_assumed(column):
    spec = classify_column("ventilation", column)
    assert spec.unit is None and spec.unit_basis is UnitBasis.UNCONFIRMED


@pytest.mark.parametrize("column", fx.SURROUNDING_HEADER[1:])
def test_surrounding_temperature_units_are_unconfirmed(column):
    spec = classify_column("surrounding_temperatures", column)
    assert spec.unit is None and spec.unit_basis is UnitBasis.UNCONFIRMED


def test_timestamp_columns_are_recognised_and_not_measurements():
    assert classify_column("temperature_power_25", "Time [Date/Time]").provenance is None
    assert classify_column("ventilation", "time").kind == "timestamp"


@pytest.mark.parametrize(
    ("key", "column"),
    [
        ("temperature_power_25", "Power Ch 4 (kW)"),
        ("temperature_power_25", "Temperature mod x ch 1"),
        ("air_speed_25", "velocity"),
        ("ventilation", "AHU_flow"),
        ("air_speed_25", "Power Ch 1 (W)"),  # right pattern, wrong file
        ("unknown_key", "Power Ch 1 (W)"),
    ],
)
def test_unrecognised_columns_are_not_guessed(key, column):
    assert classify_column(key, column) is None


# ---------------------------------------------------------------------------------------------- guard
def test_guard_passes_when_nothing_changes(raw_dir, fixture_registry):
    with RawDataGuard(raw_dir) as g:
        for p in raw_dir.glob("*.csv"):
            p.read_bytes()
    assert g.diff == {"added": [], "removed": [], "modified": []}


def test_guard_detects_modification_addition_and_removal(raw_dir, fixture_registry):
    victim = next(raw_dir.glob("*air_speed*.csv"))
    with pytest.raises(RawDataModified) as e:
        with RawDataGuard(raw_dir):
            with victim.open("ab") as fh:
                fh.write(b"x")
    assert e.value.diff["modified"] == [victim.name]

    with pytest.raises(RawDataModified) as e:
        with RawDataGuard(raw_dir):
            (raw_dir / "new.csv").write_text("a,b\n", encoding="utf-8")
    assert e.value.diff["added"] == ["new.csv"]

    with pytest.raises(RawDataModified) as e:
        with RawDataGuard(raw_dir):
            (raw_dir / "new.csv").unlink()
    assert e.value.diff["removed"] == ["new.csv"]


def test_guard_detects_a_same_size_rewrite_through_mtime(raw_dir, fixture_registry):
    victim = next(raw_dir.glob("*ventilation*.csv"))
    data = victim.read_bytes()
    with pytest.raises(RawDataModified):
        with RawDataGuard(raw_dir):
            victim.write_bytes(data)  # identical bytes, new mtime
            os.utime(victim, ns=(victim.stat().st_atime_ns, victim.stat().st_mtime_ns + 5_000_000_000))


def test_guard_does_not_mask_the_original_exception(raw_dir, fixture_registry):
    with pytest.raises(ZeroDivisionError):
        with RawDataGuard(raw_dir):
            (raw_dir / "x.csv").write_text("a\n", encoding="utf-8")
            1 / 0  # noqa: B018


def test_guard_on_a_missing_directory_is_a_no_op(tmp_path):
    with RawDataGuard(tmp_path / "absent"):
        pass
    assert snapshot(tmp_path / "absent") == {}


def test_diff_snapshots_is_pure(raw_dir, fixture_registry):
    s = snapshot(raw_dir)
    assert diff_snapshots(s, s) == {"added": [], "removed": [], "modified": []}


def test_open_raw_bytes_is_read_only_and_confined(raw_dir, fixture_registry, tmp_path):
    inside = next(raw_dir.glob("*.csv"))
    with open_raw_bytes(inside, raw_dir) as fh:
        assert fh.mode == "rb"
        with pytest.raises(Exception):  # noqa: B017 - io.UnsupportedOperation
            fh.write(b"x")
    outside = tmp_path / "elsewhere.csv"
    outside.write_text("a\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        open_raw_bytes(outside, raw_dir)
    with pytest.raises(PermissionError):
        open_raw_bytes(raw_dir / ".." / "elsewhere.csv", raw_dir)
