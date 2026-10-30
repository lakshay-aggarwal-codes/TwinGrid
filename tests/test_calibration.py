"""Task 23: calibration pipeline. Everything here is SYNTHETIC: it tests the machinery (schema checks, time split,
one-shot test scoring, parameter recovery), never the physics against a facility."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from src.calibration import (
    CalibrationDataError,
    CalibrationError,
    TestBlockAlreadyScored,
    calibrate,
    from_tidy_rows,
    make_preregistration,
)
from src.calibration import fit as fitmod
from src.calibration.synthetic import synthetic_dataset
from src.physics.params import DEFAULT_PHYSICS_PARAMS as D

TRUTH = dataclasses.replace(
    D, max_it_power_kw=620.0, idle_power_fraction=0.35, cop_closed_loop=5.2, chw_approach_c=2.6, tau_air_min=14.0
)


@pytest.fixture(scope="module")
def data():
    return synthetic_dataset(TRUTH, days=6, seed=1)


@pytest.fixture(scope="module")
def prereg(data):
    return make_preregistration(data)


@pytest.fixture(scope="module")
def report(data, prereg):
    return calibrate(data, prereg, max_iter=25)


# ---------------------------------------------------------------------------------------------- recovery
def test_synthetic_parameter_recovery(report):
    p = report["parameters"]
    assert p["max_it_power_kw"]["fitted"] == pytest.approx(620.0, rel=0.03)
    assert p["idle_power_fraction"]["fitted"] == pytest.approx(0.35, abs=0.02)
    assert p["cop_closed_loop"]["fitted"] == pytest.approx(5.2, rel=0.03)
    assert p["tau_air_min"]["fitted"] == pytest.approx(14.0, rel=0.05)


def test_a_parameter_the_data_cannot_see_is_reported_not_identified(report):
    # inlet supply floor (18 C) is above chw + approach for these set-points, so the approach has no effect
    row = report["parameters"]["chw_approach_c"]
    assert row["status"] == "not identified"
    assert row["published"] == D.chw_approach_c


def test_unfitted_parameters_keep_published_values(report):
    fitted = report["fitted_params"]
    for name in ("latent_heat_j_per_kg", "capacity_margin", "cop_hybrid", "tau_chw_min", "chw_rate_limit_c_per_5min"):
        assert fitted[name] == getattr(D, name)
    assert report["fitted_params_hash"] != report["published_params_hash"]


def test_synthetic_result_never_claims_calibration(report):
    assert report["synthetic"] is True
    assert "calibrated to dataset" not in report["label"]
    assert "not a calibration" in report["label"]


def test_real_data_label_follows_the_verdict(data, prereg):
    real = dataclasses.replace(data, synthetic=False, dataset_id="UNIT-TEST-NOT-A-FACILITY")
    rep = calibrate(real, make_preregistration(real), max_iter=15)
    if rep["verdict"] == "improved":
        assert rep["label"].startswith("calibrated to dataset UNIT-TEST-NOT-A-FACILITY")
    else:
        assert rep["label"].startswith("uncalibrated")
        assert rep["failures"]


def test_report_is_json_serialisable(report):
    json.dumps(report, allow_nan=False)


# ---------------------------------------------------------------------------------------------- split and one-shot
def test_time_split_has_no_leakage(data, prereg):
    i_fit, i_val, n = prereg["split_rows"]
    assert 0 < i_fit < i_val < n == data.n_rows
    fit = fitmod._segments(data, 0, i_fit, prereg["min_segment_steps"])
    val = fitmod._segments(data, i_fit, i_val, prereg["min_segment_steps"])
    test = fitmod._segments(data, i_val, n, prereg["min_segment_steps"])
    total = lambda segs: sum(len(s.util) for s in segs)  # noqa: E731
    assert total(fit) <= i_fit and total(val) <= i_val - i_fit and total(test) <= n - i_val
    assert max(s.day for s in fit) <= min(s.day for s in test)


def test_test_block_can_only_be_scored_once(data, prereg):
    segs = fitmod._segments(data, prereg["split_rows"][1], data.n_rows, prereg["min_segment_steps"])
    scorer = fitmod._OneShotTest(segs, data.cadence_s, prereg["warmup_steps"], prereg["metrics"])
    scorer.score({"published": D})
    with pytest.raises(TestBlockAlreadyScored):
        scorer.score({"published": D})


def test_preregistration_is_tamper_evident(data, prereg):
    bad = {**prereg, "ridge_grid": [0.0]}
    with pytest.raises(CalibrationError, match="hash"):
        calibrate(data, bad)
    other = synthetic_dataset(TRUTH, days=6, seed=2)
    with pytest.raises(CalibrationError, match="differs"):
        calibrate(other, prereg)


# ---------------------------------------------------------------------------------------------- masks
def test_unobserved_rows_are_not_used(data, prereg, report):
    masked = dataclasses.replace(
        data,
        observed={**data.observed, "cooling_power_kw": data.observed["cooling_power_kw"].copy()},
        values={**data.values, "cooling_power_kw": data.values["cooling_power_kw"].copy()},
    )
    masked.observed["cooling_power_kw"][100:400] = False
    masked.values["cooling_power_kw"][100:400] = np.nan
    pre = make_preregistration(masked)
    rep = calibrate(masked, pre, max_iter=10)
    assert rep["fit_rows_used"] < report["fit_rows_used"]


# ---------------------------------------------------------------------------------------------- schema
def _row(ts, ch, val, unit):
    return {"ts": ts, "channel": ch, "value": val, "unit": unit, "quality": "ok"}


def _rows(n=4, **over):
    out = []
    units = {
        "utilisation": "fraction",
        "outside_temp_c": "degC",
        "humidity_pct": "percent",
        "chw_requested_c": "degC",
        "it_power_kw": "kW",
        "t_in_c": "degC",
        "t_out_c": "degC",
        "cooling_power_kw": "kW",
    }
    vals = {
        "utilisation": 0.5,
        "outside_temp_c": 20.0,
        "humidity_pct": 50.0,
        "chw_requested_c": 10.0,
        "it_power_kw": 300.0,
        "t_in_c": 20.0,
        "t_out_c": 30.0,
        "cooling_power_kw": 70.0,
    }
    for i in range(n):
        ts = f"2026-01-05T00:{5 * i:02d}:00+00:00"
        for ch, u in units.items():
            out.append(_row(ts, ch, over.get(ch, vals[ch]), u))
        out.append(_row(ts, "cooling_mode", "closed_loop", "enum"))
    return out


def test_tidy_import_happy_path_counts_duplicates():
    rows = _rows() + [_row("2026-01-05T00:00:00+00:00", "it_power_kw", 999.0, "kW")]
    d = from_tidy_rows(rows, dataset_id="x", cadence_s=300)
    assert d.n_rows == 4 and d.report["duplicates"] == 1
    assert d.values["it_power_kw"][0] == 300.0  # first kept


def test_timezone_less_timestamps_are_rejected():
    rows = _rows()
    rows[0]["ts"] = "2026-01-05T00:00:00"
    with pytest.raises(CalibrationDataError, match="timezone"):
        from_tidy_rows(rows, dataset_id="x", cadence_s=300)


def test_wrong_unit_and_unknown_channel_are_rejected():
    rows = _rows()
    rows[0]["unit"] = "degF"
    with pytest.raises(CalibrationDataError, match="unit"):
        from_tidy_rows(rows, dataset_id="x", cadence_s=300)
    with pytest.raises(CalibrationDataError, match="unknown channel"):
        from_tidy_rows([_row("2026-01-05T00:00:00+00:00", "rack_7_temp", 20, "degC")], dataset_id="x", cadence_s=300)


def test_out_of_range_values_are_flagged_not_clipped():
    d = from_tidy_rows(_rows(t_in_c=80.0), dataset_id="x", cadence_s=300)
    assert d.report["out_of_range_flagged"]["t_in_c"] == 4
    assert not d.observed["t_in_c"].any()
    assert np.isnan(d.values["t_in_c"]).all()


def test_cadence_mismatch_is_rejected():
    with pytest.raises(CalibrationDataError, match="cadence"):
        from_tidy_rows(_rows(), dataset_id="x", cadence_s=60)
