"""Phase 2: data configuration, source discovery (registered files only), channel declarations, timestamp parsing."""

import numpy as np
import p2_fixtures as p2
import pandas as pd
import pytest
import synthetic_fixtures as fx

from research.danish_aau.evaluation.data_layer import timeparse
from research.danish_aau.evaluation.data_layer.channels import resolve_channels
from research.danish_aau.evaluation.data_layer.config import (
    DEFAULT_CHUNKSIZE,
    ReaderSection,
    load_data_config,
    parse_data_config,
    resolve_duplicate_policy,
)
from research.danish_aau.evaluation.data_layer.discovery import discover_sources
from research.danish_aau.evaluation.data_layer.errors import DataConfigError, DiscoveryError
from research.danish_aau.evaluation.paths import DANISH_AAU_DIR
from research.danish_aau.evaluation.registry import DEFAULT_REGISTRY


# ------------------------------------------------------------------------------------------------ config
def test_default_chunksize_is_50000():
    assert DEFAULT_CHUNKSIZE == 50_000 == ReaderSection().chunksize


def test_shipped_data_config_declares_the_authorised_decisions():
    cfg = load_data_config(DANISH_AAU_DIR / "config" / "data.toml")
    assert cfg.reader.chunksize == 50_000
    assert cfg.timestamps.state == "naive_unspecified"
    assert cfg.policies.duplicates == "keep_all_ordered"
    assert cfg.policies.approved_sensitivity == () and cfg.policies.approved_bucket_reducers == ()
    assert cfg.files["ventilation"].measurement_columns == tuple(p2.VENT_COLUMNS)
    assert cfg.reader.non_numeric == "raise" and cfg.reader.na_values == ("",)


@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        ({"reader": {"chunk_size": 5}}, "reader.chunk_size"),
        ({"surprise": {}}, "surprise"),
        ({"reader": {"chunksize": 0}}, "chunksize"),
        ({"reader": {"chunksize": True}}, "chunksize"),
        ({"reader": {"non_numeric": "coerce"}}, "non_numeric"),
        ({"reader": {"timestamp_formats": []}}, "at least one format"),
        ({"reader": {"timestamp_formats": ["%Y-%m-%d %H:%M:%S%z"]}}, "timezone directive"),
        ({"reader": {"timestamp_formats": ["%Y-%m-%d %H:%M:%S %Z"]}}, "timezone directive"),
        ({"reader": {"timestamp_formats": ["no directives"]}}, "no strptime"),
        ({"reader": {"delimiter": ";;"}}, "delimiter"),
        ({"timestamps": {"state": "UTC"}}, "naive_unspecified"),
        ({"timestamps": {"state": "Europe/Copenhagen"}}, "naive_unspecified"),
        ({"policies": {"duplicates": "mean"}}, "DIFFERENT"),
        ({"policies": {"duplicates": "keep_first"}}, "DIFFERENT"),
        ({"policies": {"duplicates": "keep_last"}}, "DIFFERENT"),
        ({"policies": {"duplicates": "whatever"}}, "policies.duplicates"),
        ({"policies": {"duplicates": "exclude_ambiguous"}}, "approved_sensitivity"),
        ({"policies": {"approved_sensitivity": ["mean_reduction"]}}, "unknown policy"),
        ({"policies": {"approved_bucket_reducers": ["median"]}}, "unknown reducer"),
        ({"policies": {"empty_rows": "drop_silently"}}, "empty_rows"),
        ({"window": {"start": "yesterday"}}, "window.start"),
        ({"files": {"x": {"measurement_columns": ["a", "a"]}}}, "duplicates"),
        ({"files": {"x": {"nope": 1}}}, "files.x.nope"),
        ({"files": {"bad key": {}}}, "files.bad key"),
        ({"schema_version": 2}, "schema_version"),
    ],
)
def test_invalid_data_configurations_are_rejected(raw, needle):
    with pytest.raises(DataConfigError) as e:
        parse_data_config(raw)
    assert needle in str(e.value)


def test_every_problem_is_reported_together():
    with pytest.raises(DataConfigError) as e:
        parse_data_config(
            {"reader": {"chunksize": -1, "non_numeric": "x"}, "policies": {"duplicates": "mean"}, "bogus": 1}
        )
    assert len(e.value.problems) >= 4


def test_sensitivity_policy_is_selectable_only_when_approved():
    cfg = parse_data_config(
        {"policies": {"duplicates": "exclude_ambiguous", "approved_sensitivity": ["exclude_ambiguous"]}}
    )
    assert cfg.policies.duplicates == "exclude_ambiguous"


def test_malformed_and_missing_files(tmp_path):
    with pytest.raises(DataConfigError):
        load_data_config(tmp_path / "nope.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("= not toml", encoding="utf-8")
    with pytest.raises(DataConfigError):
        load_data_config(bad)


def test_data_config_hash_is_stable_and_sensitive():
    a, b = parse_data_config({}), parse_data_config({})
    assert a.sha256 == b.sha256 and len(a.sha256) == 64
    assert parse_data_config({"reader": {"chunksize": 7}}).sha256 != a.sha256


def test_duplicate_policy_resolution_against_the_phase1_config():
    cfg = parse_data_config({})
    policy, note = resolve_duplicate_policy(cfg, "undeclared")
    assert policy == "keep_all_ordered" and "undeclared" in note
    assert resolve_duplicate_policy(cfg, "keep_all_ordered")[0] == "keep_all_ordered"
    with pytest.raises(DataConfigError) as e:
        resolve_duplicate_policy(cfg, "exclude_ambiguous")
    assert "conflicting duplicate policy" in str(e.value)


# ------------------------------------------------------------------------------------------------ discovery
def test_discovery_finds_the_four_registered_files_only(raw_dir, fixture_registry):
    fx.write_csv(
        raw_dir / "AAU_temperature_and_power_use_50_percent_load_period.csv",
        ["Time [Date/Time]", "a"],
        [["2024-01-01 00:00:00", 1]],
    )
    found = discover_sources(raw_dir, fixture_registry)
    assert sorted(found) == sorted(e.key for e in fixture_registry)
    assert all("50_percent" not in s.filename for s in found.values())


def test_requesting_an_unregistered_file_is_an_error(raw_dir, fixture_registry):
    with pytest.raises(DiscoveryError) as e:
        discover_sources(raw_dir, fixture_registry, ["temperature_power_50"])
    assert "not registered" in str(e.value)


def test_missing_and_ambiguous_registered_files(raw_dir, fixture_registry):
    name = fixture_registry[0].filename
    (raw_dir / name).unlink()
    with pytest.raises(DiscoveryError):
        discover_sources(raw_dir, fixture_registry, [fixture_registry[0].key])
    assert fixture_registry[0].key not in discover_sources(raw_dir, fixture_registry, missing_ok=True)
    (raw_dir / "a").mkdir()
    (raw_dir / "b").mkdir()
    for sub in ("a", "b"):
        fx.write_csv(raw_dir / sub / name, fx.MAIN_HEADER, [])
    with pytest.raises(DiscoveryError):
        discover_sources(raw_dir, fixture_registry, [fixture_registry[0].key])


def test_missing_raw_directory(tmp_path):
    with pytest.raises(DiscoveryError):
        discover_sources(tmp_path / "absent", DEFAULT_REGISTRY)
    assert discover_sources(tmp_path / "absent", DEFAULT_REGISTRY, missing_ok=True) == {}


# ------------------------------------------------------------------------------------------------ channels
def test_channels_default_to_all_non_timestamp_columns_and_carry_no_invented_units(raw_dir, fixture_registry):
    cfg = parse_data_config({})
    src = discover_sources(raw_dir, fixture_registry, ["temperature_power_25"])["temperature_power_25"]
    ch = resolve_channels(src, cfg)
    assert ch.timestamp_column == "Time [Date/Time]" and len(ch.measurement_columns) == 51
    assert (ch.info("Power Ch 1 (W)").unit, ch.info("Power Ch 1 (W)").unit_basis) == ("W", "csv_header")
    assert ch.info("Temperature mod 2 ch 3").unit_basis == "paper_context"


def test_ventilation_channels_have_unconfirmed_units(raw_dir, fixture_registry):
    src = discover_sources(raw_dir, fixture_registry, ["ventilation"])["ventilation"]
    ch = resolve_channels(src, parse_data_config(p2.VENT_CFG))
    assert ch.measurement_columns == tuple(p2.VENT_COLUMNS)
    assert all(ch.info(c).unit is None and ch.info(c).unit_basis == "unconfirmed" for c in ch.measurement_columns)


def test_unclassified_columns_are_kept_and_flagged(tmp_path):
    reader, _ = p2.build_reader(tmp_path, p2.MAIN_KEY, ["Time [Date/Time]", "mystery"], [[p2.ts(0), "1"]])
    info = reader.channels.info("mystery")
    assert info.classified is False and info.unit is None


def test_channel_configuration_errors(raw_dir, fixture_registry):
    src = discover_sources(raw_dir, fixture_registry, ["ventilation"])["ventilation"]
    with pytest.raises(DataConfigError):
        resolve_channels(src, parse_data_config({"files": {"ventilation": {"measurement_columns": ["nope"]}}}))
    with pytest.raises(DataConfigError):
        resolve_channels(src, parse_data_config({"files": {"ventilation": {"measurement_columns": ["time"]}}}))


# ------------------------------------------------------------------------------------------------ timestamp parsing
FMT = ("%Y-%m-%d %H:%M:%S",)


def _parse(values, formats=FMT, strip=True):
    ns, status = timeparse.parse_naive_timestamps(pd.Series(values), formats, strip)
    return ns, status


def test_valid_empty_and_invalid_timestamps():
    ns, st = _parse(
        [
            "2024-09-17 09:40:00",
            "",
            "   ",
            "2024-09-17T09:40:00",
            "2024-02-30 00:00:00",
            "garbage",
            "2024-09-17 09:40:00Z",
        ]
    )
    assert list(st) == [
        timeparse.OK,
        timeparse.EMPTY,
        timeparse.EMPTY,
        timeparse.ERROR,
        timeparse.ERROR,
        timeparse.ERROR,
        timeparse.TZ_SUFFIX,
    ]
    assert ns[0] != timeparse.NAT_NS and all(ns[i] == timeparse.NAT_NS for i in range(1, 7))


def test_naive_text_is_taken_as_written_with_no_timezone_conversion():
    ns, _ = _parse(["1970-01-01 00:00:01"])
    assert ns[0] == 1_000_000_000  # seconds since a naive epoch; nothing shifted for any zone


def test_formats_are_explicit_and_tried_in_order():
    ns, st = _parse(["2024-09-17 09:40:00", "17/09/2024 09:40:00"], ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"))
    assert list(st) == [timeparse.OK, timeparse.OK] and ns[0] == ns[1]
    _, st = _parse(["2024-09-17 09:40:00.500"], FMT)
    assert st[0] == timeparse.ERROR  # fractional seconds are not guessed
    _, st = _parse(["2024-09-17 09:40:00.500"], ("%Y-%m-%d %H:%M:%S.%f",))
    assert st[0] == timeparse.OK


def test_whitespace_policy_is_configurable():
    assert _parse([" 2024-09-17 09:40:00 "], strip=True)[1][0] == timeparse.OK
    assert _parse([" 2024-09-17 09:40:00 "], strip=False)[1][0] == timeparse.ERROR


def test_timestamp_parsing_returns_numpy_int64():
    ns, st = _parse(["2024-09-17 09:40:00"])
    assert ns.dtype == np.int64 and st.dtype == np.int8
