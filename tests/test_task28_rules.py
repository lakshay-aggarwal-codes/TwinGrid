"""Task 28: the work-order rules and the asset-health indicator. Pure: no database, no FastAPI, no clock."""

from __future__ import annotations

import math

import pytest

from src import maintenance_health as H
from src import work_orders as W

T0 = 1_700_000_000.0  # an arbitrary instant; samples every 5 minutes


def ramp(n: int, start: float, step: float, *, ok=lambda i: True):
    return [(T0 + i * 300.0, start + i * step, ok(i)) for i in range(n)]


# ----------------------------------------------------------------------------- work-order flow


def test_the_status_table_is_exactly_the_documented_flow():
    assert W.STATUSES == ("open", "in_progress", "done", "cancelled")
    assert W.TRANSITIONS == {
        "open": ("in_progress", "cancelled"),
        "in_progress": ("open", "done", "cancelled"),
        "done": (),
        "cancelled": (),
    }


@pytest.mark.parametrize(
    "a,b",
    [
        ("open", "in_progress"),
        ("open", "cancelled"),
        ("in_progress", "open"),
        ("in_progress", "done"),
        ("in_progress", "cancelled"),
    ],
)
def test_allowed_moves_pass(a, b):
    W.check_transition(a, b)


@pytest.mark.parametrize("a,b", [("open", "done"), ("open", "open"), ("in_progress", "in_progress")])
def test_other_moves_between_live_statuses_are_refused(a, b):
    with pytest.raises(W.TransitionError) as e:
        W.check_transition(a, b)
    assert e.value.code == "not_allowed"


@pytest.mark.parametrize("final", ["done", "cancelled"])
@pytest.mark.parametrize("target", ["open", "in_progress", "done", "cancelled"])
def test_a_final_order_cannot_move_at_all(final, target):
    with pytest.raises(W.TransitionError) as e:
        W.check_transition(final, target)
    assert e.value.code == "final"


def test_unknown_statuses_are_refused():
    for a, b in (("open", "closed"), ("weird", "open")):
        with pytest.raises(W.TransitionError) as e:
            W.check_transition(a, b)
        assert e.value.code == "not_allowed"


def test_next_statuses_mirrors_the_table():
    assert W.next_statuses("open") == ("in_progress", "cancelled")
    assert W.next_statuses("done") == ()
    assert W.next_statuses("nonsense") == ()


# ----------------------------------------------------------------------------- roles, origin, titles


def test_a_viewer_reads_only_and_an_operator_or_admin_writes():
    assert [W.can_write(r) for r in ("viewer", "operator", "admin", None, "root")] == [False, True, True, False, False]


def test_origin_is_simulated_for_alert_and_health_and_manual_otherwise():
    assert W.origin_for("manual") == "manual"
    assert W.origin_for("alert") == "simulated"
    assert W.origin_for("health") == "simulated"
    assert "measured" not in (W.origin_for(k) for k in W.SOURCE_KINDS)


def test_default_titles_are_bounded_and_say_what_they_are():
    assert W.title_from_alert("anomaly", "Outlet temperature high") == "Investigate: Outlet temperature high"
    assert W.title_from_alert("anomaly", "  ") == "Investigate alert: anomaly"
    long = W.title_from_alert("x", "m" * 500)
    assert len(long) <= W.MAX_TITLE_CHARS and long.endswith("…")
    assert W.title_from_health("Facility", "it_power_kw", "warning") == "Check Facility (it_power_kw): health warning"
    assert W.title_from_health("Rack 7", None, "watch") == "Check Rack 7: health watch"
    assert "dispatches nothing" in W.RECORD_LABEL


# ----------------------------------------------------------------------------- health: golden numbers


def test_a_steady_sensor_is_ok_with_a_flat_trend():
    s = H.summarize_sensor(ramp(40, 50.0, 0.0), 0.0, 100.0, unit="kW")
    assert s["status"] == "ok" and s["reasons"] == []
    assert s["valid_samples"] == 40 and s["invalid_share"] == 0.0
    assert s["trend"]["direction"] == "flat" and s["trend"]["drift_pct_of_range"] == pytest.approx(0.0)
    assert s["latest"]["value"] == 50.0
    assert s["unit"] == "kW"


def test_a_ramp_reports_the_fitted_trend_exactly():
    # +1 unit per 5 min over 40 samples: 39 units over the span, valid range 100 -> 39 % of the range.
    s = H.summarize_sensor(ramp(40, 10.0, 1.0), 0.0, 100.0)
    t = s["trend"]
    assert t["slope_per_day"] == pytest.approx(288.0)  # 1 per 300 s
    assert t["change_over_window"] == pytest.approx(39.0)
    assert t["span_hours"] == pytest.approx(39 * 300 / 3600)
    assert t["drift_pct_of_range"] == pytest.approx(39.0)
    assert t["direction"] == "up"
    assert s["status"] == "warning" and "39%" in s["reasons"][0]


def test_a_falling_sensor_trends_down():
    s = H.summarize_sensor(ramp(40, 90.0, -0.5), 0.0, 100.0)
    assert s["trend"]["direction"] == "down" and s["trend"]["slope_per_day"] < 0
    assert s["status"] == "watch"  # 19.5 % of the range: between 10 and 25


@pytest.mark.parametrize("step,expected", [(0.1, "ok"), (0.5, "watch"), (1.0, "warning")])
def test_drift_bands(step, expected):
    # 39 steps over a valid range of 100: 3.9 %, 19.5 % and 39 % of the range (bands: watch from 10 %, warning from 25 %).
    assert H.summarize_sensor(ramp(40, 10.0, step), 0.0, 100.0)["status"] == expected


def test_the_band_edges_are_inclusive():
    assert H.DRIFT_WATCH_PCT == 10.0 and H.DRIFT_WARNING_PCT == 25.0
    edge = 25.0 / 39.0  # a drift of exactly 25 % of the range over 39 steps
    assert H.summarize_sensor(ramp(40, 10.0, edge), 0.0, 100.0)["status"] == "warning"
    assert H.summarize_sensor(ramp(40, 10.0, edge * 0.99), 0.0, 100.0)["status"] == "watch"


def test_invalid_share_bands():
    def with_invalid(k):  # k invalid samples out of 40
        return H.summarize_sensor(ramp(40, 50.0, 0.0, ok=lambda i: i >= k), 0.0, 100.0)

    assert with_invalid(1)["status"] == "ok"  # 2.5 %
    assert with_invalid(2)["status"] == "watch"  # 5 %
    assert with_invalid(7)["status"] == "watch"  # 17.5 %
    assert with_invalid(8)["status"] == "warning"  # 20 %
    assert with_invalid(8)["invalid_share"] == pytest.approx(0.2)


def test_the_latest_valid_value_outside_the_valid_range_is_a_warning():
    s = H.summarize_sensor(ramp(30, 90.0, 0.0) + [(T0 + 30 * 300, 120.0, True)], 0.0, 100.0)
    assert s["status"] == "warning"
    assert any("outside the sensor's valid range" in r for r in s["reasons"])


def test_too_few_valid_samples_is_not_measured_never_ok():
    s = H.summarize_sensor(ramp(H.MIN_SAMPLES - 1, 50.0, 0.0), 0.0, 100.0)
    assert s["status"] == "no_data" and s["trend"] is None and s["latest"] is None and s["series"] == []
    assert "NOT MEASURED" in s["reasons"][0]
    assert H.summarize_sensor([], 0.0, 100.0)["status"] == "no_data"
    # invalid samples do not count towards the minimum
    assert H.summarize_sensor(ramp(40, 50.0, 0.0, ok=lambda i: i < 5), 0.0, 100.0)["status"] == "no_data"


def test_without_a_valid_range_there_is_a_slope_but_no_drift_percentage_and_no_trend_rule():
    s = H.summarize_sensor(ramp(40, 10.0, 5.0), None, None)
    assert s["trend"]["slope_per_day"] > 0 and s["trend"]["drift_pct_of_range"] is None
    assert s["status"] == "ok"


def test_a_non_finite_value_is_not_counted_as_valid():
    samples = ramp(40, 50.0, 0.0)
    samples[10] = (samples[10][0], math.nan, True)
    s = H.summarize_sensor(samples, 0.0, 100.0)
    assert s["valid_samples"] == 39 and s["invalid_share"] == pytest.approx(1 / 40)


def test_unordered_input_gives_the_same_answer():
    a = ramp(40, 10.0, 1.0)
    assert H.summarize_sensor(list(reversed(a)), 0.0, 100.0) == H.summarize_sensor(a, 0.0, 100.0)


def test_the_series_is_bounded_ordered_and_averaged():
    s = H.summarize_sensor(ramp(500, 0.0, 0.1), 0.0, 1000.0)
    ts = [p["t"] for p in s["series"]]
    assert 1 < len(ts) <= H.MAX_SERIES_POINTS and ts == sorted(ts)
    assert s["series"][0]["v"] < s["series"][-1]["v"]
    assert ts[0].endswith("+00:00")  # UTC


def test_identical_input_gives_identical_output():
    a = H.summarize_sensor(ramp(60, 20.0, 0.3, ok=lambda i: i % 9 != 0), 0.0, 100.0)
    assert a == H.summarize_sensor(ramp(60, 20.0, 0.3, ok=lambda i: i % 9 != 0), 0.0, 100.0)


# ----------------------------------------------------------------------------- health: per asset


def test_an_asset_is_as_bad_as_its_worst_sensor_with_data():
    ok = {"status": "ok"}
    assert H.asset_status([ok, {"status": "watch"}, {"status": "no_data"}]) == "watch"
    assert H.asset_status([ok, {"status": "warning"}, {"status": "watch"}]) == "warning"
    assert H.asset_status([{"status": "no_data"}, {"status": "no_data"}]) == "no_data"
    assert H.asset_status([]) == "no_data"


def test_assets_without_sensors_are_not_measured_and_every_row_says_no_remaining_life():
    good = H.summarize_sensor(ramp(40, 50.0, 0.0), 0.0, 100.0)
    rows = H.build_assets(
        [
            {"id": 1, "external_id": "facility-level", "name": "Facility", "asset_type": "facility"},
            {"id": 2, "external_id": "rack-1", "name": "rack-1", "asset_type": "rack"},
        ],
        {1: [{"measurand": "it_power_kw", "external_id": "fac1.it_power_kw", "summary": good}]},
    )
    fac, rack = rows
    assert fac["status"] == "ok" and fac["sensor_count"] == 1 and fac["sensors"][0]["measurand"] == "it_power_kw"
    assert rack["status"] == "no_data" and rack["sensors"] == [] and "NOT MEASURED" in rack["note"]
    for r in rows:
        assert r["remaining_life"]["available"] is False and "C-MAPSS" in r["remaining_life"]["reason"]
    assert H.counts(rows) == {"ok": 1, "watch": 0, "warning": 0, "no_data": 1}


def test_the_label_says_what_this_is_not():
    assert "not a failure prediction" in H.LABEL and "simulated" in H.LABEL
    assert H.REMAINING_LIFE["available"] is False
