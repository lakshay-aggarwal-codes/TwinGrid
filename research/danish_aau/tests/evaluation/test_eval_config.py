"""Strict configuration parsing and the explicit scientific declarations."""

import pytest

from research.danish_aau.evaluation.config import ConfigError, load_config, parse_config
from research.danish_aau.evaluation.paths import DEFAULT_CONFIG_PATH


def test_shipped_default_config_loads_and_is_not_ready_for_comparisons():
    cfg = load_config(DEFAULT_CONFIG_PATH)
    assert cfg.timestamps.timezone == "undeclared"
    assert cfg.policies.duplicate_timestamps == "undeclared"
    ready = cfg.readiness()
    assert ready["ready_for_comparisons"] is False
    assert len(ready["blocking"]) == 2


def test_empty_mapping_gives_defaults():
    assert parse_config({}).run.name == "aau_eval"


def test_declaring_both_makes_comparisons_ready():
    cfg = parse_config(
        {
            "timestamps": {"timezone": "Europe/Copenhagen", "timezone_basis": "logger documentation says local time"},
            "policies": {"duplicate_timestamps": "keep_all_ordered"},
        }
    )
    assert cfg.readiness() == {"ready_for_comparisons": True, "blocking": []}


def test_unknown_key_and_section_are_errors():
    with pytest.raises(ConfigError) as e:
        parse_config({"run": {"nmae": "typo"}, "surprise": {}})
    assert any("run.nmae" in p for p in e.value.problems)
    assert any("surprise" in p for p in e.value.problems)


def test_all_problems_are_reported_together():
    with pytest.raises(ConfigError) as e:
        parse_config({"run": {"name": "bad name!", "seed": -1}, "policies": {"interpolation": "linear"}})
    assert len(e.value.problems) >= 3


def test_type_errors_including_bool_for_int():
    with pytest.raises(ConfigError):
        parse_config({"run": {"seed": True}})
    with pytest.raises(ConfigError):
        parse_config({"integrity": {"hash_inputs": "yes"}})


@pytest.mark.parametrize("policy", ["mean", "average", "first", "last", "keep_first", "keep_last", "drop", "dedupe"])
def test_silent_duplicate_policies_are_rejected_with_the_reason(policy):
    with pytest.raises(ConfigError) as e:
        parse_config({"policies": {"duplicate_timestamps": policy}})
    assert "DIFFERENT" in str(e.value)


def test_unknown_duplicate_policy_is_rejected():
    with pytest.raises(ConfigError):
        parse_config({"policies": {"duplicate_timestamps": "whatever"}})


def test_declared_timezone_requires_a_basis():
    with pytest.raises(ConfigError) as e:
        parse_config({"timestamps": {"timezone": "UTC"}})
    assert "timezone_basis" in str(e.value)


@pytest.mark.parametrize("tz", ["UTC", "Europe/Copenhagen", "+02:00", "-05:30"])
def test_accepted_timezone_forms(tz):
    assert parse_config({"timestamps": {"timezone": tz, "timezone_basis": "b"}}).timestamps.timezone == tz


@pytest.mark.parametrize("tz", ["CEST", "2", "+25:00", "Copenhagen", ""])
def test_rejected_timezone_forms(tz):
    with pytest.raises(ConfigError):
        parse_config({"timestamps": {"timezone": tz, "timezone_basis": "b"}})


def test_only_the_audited_load_period_is_selectable():
    with pytest.raises(ConfigError):
        parse_config({"dataset": {"load_period": "50_percent"}})


def test_ventilation_filling_is_not_selectable():
    with pytest.raises(ConfigError):
        parse_config({"policies": {"ventilation_missing": "forward_fill"}})


def test_schema_version_is_checked():
    with pytest.raises(ConfigError):
        parse_config({"schema_version": 2})


def test_config_hash_is_stable_and_sensitive():
    a, b = parse_config({}), parse_config({})
    assert a.sha256 == b.sha256 and len(a.sha256) == 64
    assert parse_config({"run": {"seed": 1}}).sha256 != a.sha256


def test_missing_and_malformed_files(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad)


def test_machine_specific_locations_do_not_change_the_config_hash_or_appear_in_it():
    a = parse_config({})
    b = parse_config({"dataset": {"raw_dir": "D:/somewhere/else"}, "output": {"root": "elsewhere"}})
    assert a.sha256 == b.sha256
    assert "raw_dir" not in b.portable_dict()["dataset"] and "root" not in b.portable_dict()["output"]
    assert b.to_dict()["dataset"]["raw_dir"] == "D:/somewhere/else"  # the full dict still has it
