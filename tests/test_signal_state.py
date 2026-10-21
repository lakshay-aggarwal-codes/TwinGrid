"""Task 16: signal state v1 (playbook 8.5). The shared fixture ``tests/fixtures/signal_state_cases.json`` is read by this
file and by ``twin-stream-insight-main/src/contract/signalState.test.ts``; their expected values were written by hand."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import signal_state as ss
from src.signal_state import SignalRule, SignalState, evaluate

FIXTURE = Path(__file__).parent / "fixtures" / "signal_state_cases.json"
DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = DOC["cases"]
NOW = datetime(2026, 10, 20, 10, 10, 0, tzinfo=timezone.utc)
BAND = SignalRule("band", warn_low=20.0, warn_high=25.0, crit_low=15.0, crit_high=30.0, unit="°C")


def parse(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text.replace("Z", "+00:00"))


def rule_of(raw: dict) -> SignalRule:
    return SignalRule(raw["rule_id"], raw["warn_low"], raw["warn_high"], raw["crit_low"], raw["crit_high"], raw["unit"])


# ------------------------------------------------------------------------------------------ shared fixture parity
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_shared_fixture_case(case):
    i = case["input"]
    got = evaluate(
        i["value"], parse(i["observed_at"]), parse(i["now"]), rule_of(i["rule"]), i["stale_after_s"], i["connected"]
    )
    assert got.to_dict() == case["expected"], case["description"]


def test_the_fixture_covers_every_status_and_every_reason_code_except_the_adapter_one():
    statuses = {c["expected"]["status"] for c in CASES}
    reasons = {c["expected"]["reason_code"] for c in CASES}
    assert statuses == set(ss.STATUSES)
    assert reasons == set(ss.REASON_CODES) - {
        "rule_unavailable"
    }  # that one is produced by callers (``unavailable``), not ``evaluate``
    assert len({c["id"] for c in CASES}) == len(CASES)


def test_every_expected_value_is_internally_consistent():
    """Guards the hand-written fixture itself, independent of ``evaluate``."""
    for c in CASES:
        e = c["expected"]
        assert e["status"] in ss.STATUSES and e["reason_code"] in ss.REASON_CODES
        if e["status"] in {"unknown", "offline"}:
            assert e["value"] is None  # never a number for unknown / offline
        if e["status"] == "stale":
            assert e["value"] is not None and e["age_s"] > c["input"]["stale_after_s"]
        if e["status"] in {"warning", "critical"}:
            assert e["threshold"] is not None and e["age_s"] <= c["input"]["stale_after_s"]
        if e["status"] == "normal":
            assert e["reason_code"] == "within_bounds" and e["threshold"] is None


# ------------------------------------------------------------------------------------------ precedence and properties
def fresh(value, age=1.0, rule=BAND, **kw):
    return evaluate(value, NOW - timedelta(seconds=age), NOW, rule, kw.pop("stale", 10), **kw)


def test_precedence_order_is_no_value_then_stale_then_critical_then_warning_then_normal():
    assert fresh(None).status == "unknown"
    assert fresh(None, connected=False).status == "offline"
    assert fresh(99.0, age=60).status == "stale"  # stale beats critical
    assert fresh(31.0).status == "critical"  # critical beats warning for a value past both bounds
    assert fresh(26.0).status == "warning"
    assert fresh(22.0).status == "normal"


@pytest.mark.parametrize("value", [-1e9, 0.0, 14.9, 19.9, 22.0, 25.1, 30.1, 1e9])
@pytest.mark.parametrize("age", [10.001, 11, 3600, 1e7])
def test_an_old_reading_is_never_normal_and_never_a_current_alarm(value, age):
    got = fresh(value, age=age)
    assert got.status == "stale" and got.reason_code == "too_old"
    assert got.status not in {"normal", "warning", "critical"} and got.threshold is None


@pytest.mark.parametrize("connected", [True, False])
@pytest.mark.parametrize("observed", [None, NOW - timedelta(seconds=1), NOW - timedelta(days=3)])
def test_unknown_and_offline_never_carry_a_number(connected, observed):
    got = evaluate(None, observed, NOW, BAND, 10, connected)
    assert got.status == ("unknown" if connected else "offline") and got.value is None and got.threshold is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_value_is_treated_as_no_value(value):
    got = fresh(value)
    assert got.status == "unknown" and got.reason_code == "no_value" and got.value is None
    assert evaluate(value, NOW, NOW, BAND, 10, connected=False).status == "offline"


def test_a_number_without_an_observation_time_is_not_shown_as_current():
    got = evaluate(22.0, None, NOW, BAND, 10)
    assert (got.status, got.reason_code, got.value, got.age_s) == ("unknown", "no_value", None, None)


def test_age_is_in_whole_milliseconds_and_clamped_at_zero():
    assert (
        evaluate(1.0, NOW - timedelta(seconds=1, microseconds=499100), NOW, SignalRule("r"), 10).age_s == 1.5
    )  # observed ...58.500900 -> 500 ms
    assert evaluate(1.0, NOW + timedelta(hours=2), NOW, SignalRule("r"), 10).age_s == 0.0


def test_a_naive_timestamp_is_refused_not_guessed():
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate(1.0, datetime(2026, 10, 20, 10, 0, 0), NOW, SignalRule("r"), 10)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate(1.0, NOW, datetime(2026, 10, 20, 10, 10, 0), SignalRule("r"), 10)


def test_the_result_is_frozen_and_json_ready():
    got = fresh(31.0)
    assert isinstance(got, SignalState)
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError
        got.status = "normal"  # type: ignore[misc]
    json.dumps(got.to_dict())
    assert got.to_dict()["observed_at"] == "2026-10-20T10:09:59Z"


def test_isoformat_is_canonical_utc_with_milliseconds_only_when_present():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert ss.isoformat_z(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)) == "2026-01-02T03:04:05Z"
    assert ss.isoformat_z(datetime(2026, 1, 2, 3, 4, 5, 120000, tzinfo=timezone.utc)) == "2026-01-02T03:04:05.120Z"
    assert ss.isoformat_z(datetime(2026, 1, 2, 3, 4, 5, 999999, tzinfo=timezone.utc)) == "2026-01-02T03:04:05.999Z"
    assert ss.isoformat_z(datetime(2026, 1, 2, 8, 34, 5, tzinfo=ist)) == "2026-01-02T03:04:05Z"
    assert ss.isoformat_z(None) is None


def test_unavailable_is_unknown_with_rule_unavailable_and_no_number():
    got = ss.unavailable("mystery", "kW")
    assert (got.status, got.reason_code, got.value, got.rule_id, got.unit) == (
        "unknown",
        "rule_unavailable",
        None,
        "mystery",
        "kW",
    )


# ------------------------------------------------------------------------------------------ rules derive from existing constants
def test_default_rules_are_the_safety_envelope_not_new_numbers():
    from src.digital_twin import SAFETY_ENVELOPE as env

    rules = ss.default_rules()
    assert (
        (rules["inlet_temp_c"].crit_low, rules["inlet_temp_c"].crit_high)
        == (env.inlet_min_C, env.inlet_max_C)
        == (18.0, 27.0)
    )
    assert rules["outlet_temp_c"].crit_high == env.outlet_max_C == 45.0
    assert rules["pue"].crit_high == env.pue_max == 2.0
    assert all(r.warn_low is None and r.warn_high is None for r in rules.values())  # the repo defines no warning band
    assert ss.rule_for("inlet_temp_c") == rules["inlet_temp_c"] and ss.rule_for("nope") is None


def test_the_fixture_default_rules_block_matches_the_python_rules():
    rules = ss.default_rules()
    for rule_id, raw in DOC["default_rules"].items():
        r = rules[rule_id]
        assert (r.crit_low, r.crit_high, r.unit) == (raw.get("crit_low"), raw.get("crit_high"), raw["unit"]), rule_id
    assert set(DOC["default_rules"]) == set(rules)


def test_the_envelope_rule_agrees_with_safety_envelope_violations_on_a_sweep():
    """At every fresh reading, ``critical`` <=> the existing envelope reports an inlet violation."""
    from src.digital_twin import SAFETY_ENVELOPE as env

    rule = ss.default_rules()["inlet_temp_c"]
    for tenth in range(100, 400):
        v = tenth / 10
        crit = fresh(v, rule=rule).status == "critical"
        assert crit == bool({"inlet_below_min", "inlet_above_max"} & set(env.violations(v, 30.0, 1.5))), v


# ------------------------------------------------------------------------------------------ stale window mirrors the browser
@pytest.mark.parametrize("row", DOC["stale_after"], ids=lambda r: f"interval={r['interval_s']}")
def test_stale_after_matches_the_shared_table(row):
    assert ss.stale_after_s(row["interval_s"]) == row["expected_s"]


def test_stale_after_constants_mirror_hooks_liveness_ts():
    src = (Path(__file__).parents[1] / "twin-stream-insight-main/src/hooks/liveness.ts").read_text(encoding="utf-8")
    assert f"DEFAULT_INTERVAL_S = {int(ss.DEFAULT_INTERVAL_S)}" in src
    assert f"STALE_INTERVAL_MULTIPLIER = {int(ss.STALE_INTERVAL_MULTIPLIER)}" in src
    assert f"MIN_STALE_AFTER_MS = {int(ss.MIN_STALE_AFTER_S * 1000)}" in src
    assert math.isfinite(ss.stale_after_s(float("nan"))) and ss.stale_after_s(float("nan")) == 9.0


def test_the_module_imports_the_envelope_lazily_not_at_import_time():
    import ast

    tree = ast.parse((Path(__file__).parents[1] / "src/signal_state.py").read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not [n for n in top_level if "digital_twin" in ast.dump(n)]
