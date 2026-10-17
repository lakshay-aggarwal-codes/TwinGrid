"""Task 27: carbon-aware scheduling. Flat-series and varying-series behaviour, with real ``carbon_provider`` signals
built from temporary CSV files (no network, no DB, no twin run)."""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from src import carbon_provider as CP
from src.carbon_schedule import windows as W

HEADLINE = "No carbon variation in current data"


@pytest.fixture(autouse=True)
def _utc_site(monkeypatch):
    """Site-local hour == UTC hour, so the CSV hours below are the curve's hours; and no stale memoised signal."""
    monkeypatch.setenv("SITE_TIMEZONE", "UTC")
    CP.clear_carbon_cache()
    yield
    CP.clear_carbon_cache()


def _csv(tmp_path, values_by_hour, *, semantic="average"):
    rows = [
        {"timestamp_utc": f"2026-01-01T{h:02d}:00:00Z", "zone": "TEST", "carbon_intensity_gco2_per_kwh": v}
        for h, v in values_by_hour.items()
    ]
    path = tmp_path / "carbon_intensity.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    if semantic:
        (tmp_path / CP.CARBON_META_FILENAME).write_text(json.dumps({"semantic": semantic, "source_version": "test"}))
    return CP.load_carbon_signal(path=path)


def _ramp(tmp_path, **kw):
    return _csv(tmp_path, {h: 300.0 + h for h in range(24)}, **kw)


ARGS = {"duration_h": 4, "load_kw": 100.0}


# ------------------------------------------------------------------------------------------ varying series
def test_varying_series_golden_best_window_and_savings(tmp_path):
    sig = _ramp(tmp_path)
    assert sig.is_fallback is False and sig.semantic == "average"
    r = W.suggest(sig, **ARGS)
    assert r["status"] == "ok" and r["profile"] == "data" and r["synthetic_label"] is None
    assert r["best"]["start_hour"] == 0 and r["best"]["end_hour"] == 4
    assert r["best"]["mean_gco2_per_kwh"] == pytest.approx(301.5)
    assert r["best"]["emissions_kg"] == pytest.approx(120.6)  # 100 kW x 4 h x 301.5 g/kWh
    assert r["worst"]["start_hour"] == 20 and r["worst"]["mean_gco2_per_kwh"] == pytest.approx(321.5)
    assert r["baseline"]["kind"] == "average_of_allowed_windows"
    assert r["baseline"]["mean_gco2_per_kwh"] == pytest.approx(311.5)  # every hour is in 4 of the 24 wrapped windows
    assert r["savings"]["emissions_kg"] == pytest.approx(4.0)
    assert r["savings"]["pct"] == pytest.approx(100 * 4.0 / 124.6)
    assert r["candidates"] == 24
    assert r["curve_gco2_per_kwh"][5] == pytest.approx(305.0)
    assert r["headline"] == "Lowest-carbon 4-hour window: 00:00 to 04:00 (site-local time)"


def test_varying_series_states_what_it_is_and_is_not(tmp_path):
    r = W.suggest(_ramp(tmp_path), **ARGS)
    assert r["label"] == "scheduling suggestion from an hour-of-day carbon profile, not a forecast"
    assert "not a forecast" in r["message"]
    assert W.AVERAGE_NOT_MARGINAL in r["caveats"]  # an average series is not a marginal one
    assert r["carbon"]["is_fallback"] is False and r["site_timezone"] == "UTC"
    marginal = W.suggest(_ramp(tmp_path, semantic="marginal"), **ARGS)
    assert marginal["status"] == "ok" and marginal["caveats"] == []


def test_window_inside_the_day_does_not_wrap(tmp_path):
    r = W.suggest(_ramp(tmp_path), window_start=8, window_hours=12, **ARGS)  # 08:00-20:00: starts 8..16
    assert r["candidates"] == 9
    assert r["best"]["start_hour"] == 8 and r["best"]["mean_gco2_per_kwh"] == pytest.approx(309.5)
    assert r["baseline"]["mean_gco2_per_kwh"] == pytest.approx(313.5)
    assert r["worst"]["start_hour"] == 16


def test_window_that_crosses_midnight(tmp_path):
    r = W.suggest(_ramp(tmp_path), duration_h=3, load_kw=100.0, window_start=22, window_hours=8)  # 22:00-06:00
    assert r["candidates"] == 6
    assert r["best"]["start_hour"] == 0 and r["best"]["end_hour"] == 3
    assert r["worst"]["start_hour"] == 22 and r["worst"]["mean_gco2_per_kwh"] == pytest.approx(315.0)


def test_a_run_may_wrap_past_midnight_when_any_time_is_allowed():
    curve = [400.0] * 24
    curve[23] = curve[0] = curve[1] = 300.0
    p = W.plan(curve, duration_h=3, load_kw=10.0)
    assert p["best"]["start_hour"] == 23 and p["best"]["end_hour"] == 2


def test_reference_start_is_the_baseline(tmp_path):
    r = W.suggest(_ramp(tmp_path), window_start=8, window_hours=12, reference_start_hour=10, **ARGS)
    assert r["baseline"]["kind"] == "reference_start" and r["baseline"]["start_hour"] == 10
    assert r["baseline"]["mean_gco2_per_kwh"] == pytest.approx(311.5)
    assert r["savings"]["emissions_kg"] == pytest.approx(0.8)
    best_start = W.suggest(_ramp(tmp_path), reference_start_hour=0, **ARGS)  # already at the best window
    assert best_start["savings"]["emissions_kg"] == pytest.approx(0.0)
    assert best_start["savings"]["pct"] == pytest.approx(0.0)


def test_ties_go_to_the_earliest_candidate_in_the_allowed_span():
    curve = [400.0] * 24
    curve[5] = curve[17] = 300.0
    assert W.plan(curve, duration_h=1, load_kw=1.0)["best"]["start_hour"] == 5
    assert W.plan(curve, duration_h=1, load_kw=1.0, window_start=10)["best"]["start_hour"] == 17


def test_zero_intensity_has_no_percentage():
    p = W.plan([0.0] * 24, duration_h=2, load_kw=5.0)
    assert p["savings"] == {"emissions_kg": 0.0, "pct": None}


def test_deterministic(tmp_path):
    sig = _ramp(tmp_path)
    assert W.suggest(sig, **ARGS) == W.suggest(sig, **ARGS)


# ------------------------------------------------------------------------------------------ flat series
def test_flat_fallback_constant_claims_nothing():
    r = W.suggest(CP.fallback_signal(), **ARGS)
    assert r["status"] == "no_variation" and r["headline"] == HEADLINE
    assert r["message"].startswith(HEADLINE) and "flat assumed constant" in r["message"]
    assert r["best"] is None and r["worst"] is None and r["baseline"] is None and r["savings"] is None
    assert r["curve_gco2_per_kwh"] == [475.0] * 24
    assert r["carbon"]["is_fallback"] is True and r["carbon"]["time_varying_signal"] is False
    assert r["synthetic_label"] is None and r["profile"] == "data"


def test_the_missing_carbon_file_is_that_flat_fallback(tmp_path):
    sig = CP.load_carbon_signal(path=tmp_path / "does_not_exist.csv")
    assert sig.is_fallback is True
    assert W.suggest(sig, **ARGS)["status"] == "no_variation"


def test_a_loaded_series_that_is_flat_also_claims_nothing(tmp_path):
    sig = _csv(tmp_path, {h: 300.0 for h in range(24)})
    assert sig.is_fallback is False
    r = W.suggest(sig, **ARGS)
    assert r["status"] == "no_variation" and r["headline"] == HEADLINE and r["savings"] is None and r["best"] is None
    assert "assumed constant" not in r["message"]


# ------------------------------------------------------------------------------------------ not fit to claim
def test_hours_filled_by_an_assumption_give_no_window_and_no_saving(tmp_path):
    sig = _csv(tmp_path, {h: 300.0 + h for h in range(12)})  # hours 12-23 missing: filled with the flat assumption
    assert sig.is_fallback is True and sig.missing_hours
    r = W.suggest(sig, **ARGS)
    assert r["status"] == "unverified" and "no data" in r["message"]
    assert r["best"] is None and r["savings"] is None and r["curve_gco2_per_kwh"] is None


def test_a_series_with_no_documented_meaning_gives_no_window_and_no_saving(tmp_path):
    sig = _ramp(tmp_path, semantic=None)
    assert sig.semantic == "unknown"
    r = W.suggest(sig, **ARGS)
    assert r["status"] == "unverified" and "no documented meaning" in r["message"]
    assert r["best"] is None and r["savings"] is None


# ------------------------------------------------------------------------------------------ synthetic demonstration
def test_synthetic_profile_is_labelled_and_never_looks_like_data():
    r = W.suggest(CP.fallback_signal(), profile="synthetic_demo", duration_h=3, load_kw=100.0)
    assert r["status"] == "synthetic_demo" and r["profile"] == "synthetic_demo"
    assert r["synthetic_label"] == "SYNTHETIC DEMONSTRATION profile, not grid data"
    assert r["headline"].startswith("Demonstration only: ") and "SYNTHETIC DEMONSTRATION" in r["message"]
    assert r["best"]["start_hour"] == 12 and r["best"]["end_hour"] == 15  # the synthetic trough is at 13:00
    assert r["best"]["mean_gco2_per_kwh"] == pytest.approx(W.window_mean(W.SYNTHETIC_CURVE, 12, 3))
    assert r["savings"]["emissions_kg"] > 0
    assert r["curve_gco2_per_kwh"] == list(W.SYNTHETIC_CURVE)
    assert r["carbon"]["is_fallback"] is True  # the real signal's label is still reported beside it
    assert any("Synthetic" in c for c in r["caveats"])


def test_synthetic_curve_is_a_fixed_artificial_shape():
    assert len(W.SYNTHETIC_CURVE) == 24
    assert W.SYNTHETIC_CURVE[13] == pytest.approx(355.0) and W.SYNTHETIC_CURVE[1] == pytest.approx(595.0)
    assert sum(W.SYNTHETIC_CURVE) / 24 == pytest.approx(475.0)
    assert not W.is_flat(W.SYNTHETIC_CURVE) and W.is_flat([475.0] * 24)


def test_synthetic_profile_is_independent_of_the_loaded_data(tmp_path):
    a = W.suggest(CP.fallback_signal(), profile="synthetic_demo", **ARGS)
    b = W.suggest(_ramp(tmp_path), profile="synthetic_demo", **ARGS)
    for key in ("best", "savings", "curve_gco2_per_kwh"):
        assert a[key] == b[key]


# ------------------------------------------------------------------------------------------ validation
@pytest.mark.parametrize(
    "kw",
    [
        {"duration_h": 0},
        {"duration_h": 25},
        {"duration_h": True},
        {"duration_h": 2.5},
        {"load_kw": 0.0},
        {"load_kw": -1.0},
        {"load_kw": math.nan},
        {"load_kw": math.inf},
        {"load_kw": W.MAX_LOAD_KW + 1},
        {"window_start": 24},
        {"window_start": -1},
        {"window_hours": 0},
        {"window_hours": 25},
        {"duration_h": 6, "window_hours": 5},
        {"reference_start_hour": 24},
        {"window_start": 8, "window_hours": 12, "reference_start_hour": 17},  # a 4 h run from 17:00 ends after 20:00
        {"profile": "banana"},
    ],
)
def test_bad_requests_are_refused_without_a_suggestion(kw):
    args = {"duration_h": 4, "load_kw": 100.0, **kw}
    with pytest.raises(W.ScheduleError):
        W.suggest(CP.fallback_signal(), **args)


def test_plan_refuses_a_bad_curve():
    for bad in ([1.0] * 23, [math.nan] * 24, [[1.0] * 24]):
        with pytest.raises(W.ScheduleError):
            W.plan(bad, duration_h=1, load_kw=1.0)


# ------------------------------------------------------------------------------------------ the plugin
def test_plugin_computes_from_the_loaded_signal_and_declares_its_route(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from api.plugins import carbon_schedule as C

    assert [r.path for r in C.router.routes] == ["/api/carbon/schedule"]
    assert C._limit() == "30/minute"
    monkeypatch.setattr(CP, "CLEANED_CARBON_PATH", tmp_path / "missing.csv")
    CP.clear_carbon_cache()
    flat = C.compute_schedule(4, 100.0, 0, 24, None, "data")
    assert flat["status"] == "no_variation" and flat["savings"] is None
    assert C.compute_schedule(4, 100.0, 0, 24, None, "synthetic_demo")["status"] == "synthetic_demo"
    real = _ramp(tmp_path)  # writes tmp_path/carbon_intensity.csv
    assert real.is_fallback is False
    monkeypatch.setattr(CP, "CLEANED_CARBON_PATH", tmp_path / "carbon_intensity.csv")
    CP.clear_carbon_cache()
    ok = C.compute_schedule(4, 100.0, 0, 24, None, "data")
    assert ok["status"] == "ok" and ok["best"]["start_hour"] == 0
