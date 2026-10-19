"""Task 11: ``scripts/forecast_baselines.py`` -- persistence / seasonal-naive / train-mean on the forecaster's own split.

Expected values are worked out by hand or recomputed independently in the test, never read back from the script. The
TensorFlow branch is exercised with a stand-in forecaster (the wiring, not a model); no real model is loaded or trained.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.lstm_model import DEFAULT_FEATURE_COLUMNS, TARGET_COLUMN, DataPipeline

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("forecast_baselines_under_test2", ROOT / "scripts" / "forecast_baselines.py")
FB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FB)

STEPS_PER_DAY = 288  # 5-minute cadence


def _daily_frame(days: int, *, drop: tuple[int, int] | None = None) -> pd.DataFrame:
    """Outlet temperature is an exact daily sine, so a 24 h seasonal-naive forecast is exact; the other features vary
    smoothly so the 3-sigma filter removes nothing. ``drop`` removes a block of rows (a data gap)."""
    n = days * STEPS_PER_DAY
    t = np.arange(n)
    data = {"timestamp": pd.date_range("2024-01-01", periods=n, freq="5min")}
    for i, col in enumerate(DEFAULT_FEATURE_COLUMNS):
        data[col] = 10.0 * (i + 1) + np.sin(2 * np.pi * t / STEPS_PER_DAY + i)
    data[TARGET_COLUMN] = 30.0 + 5.0 * np.sin(2 * np.pi * t / STEPS_PER_DAY)
    df = pd.DataFrame(data)
    if drop:
        df = df.drop(index=range(*drop)).reset_index(drop=True)
    return df


def _write(tmp_path: Path, df: pd.DataFrame, name: str = "d.csv") -> Path:
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


# ------------------------------------------------------------------------------------------ metrics
def test_score_by_hand():
    s = FB.score(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 5.0]))
    assert s["n"] == 3
    assert s["rmse"] == pytest.approx(math.sqrt(4.0 / 3.0))
    assert s["mae"] == pytest.approx(2.0 / 3.0)


def test_score_of_nothing_and_of_mismatched_shapes():
    assert FB.score(np.array([]), np.array([])) == {"n": 0, "rmse": None, "mae": None}
    with pytest.raises(ValueError):
        FB.score(np.zeros(3), np.zeros(4))


def test_score_uses_the_same_arithmetic_as_the_forecasters_evaluate():
    """``ThermalForecaster.evaluate`` is sqrt(mean(err^2)) and mean(|err|) on the unscaled target."""
    rng = np.random.default_rng(3)
    p, y = rng.normal(30, 2, 500), rng.normal(30, 2, 500)
    s = FB.score(p, y)
    assert s["rmse"] == pytest.approx(float(np.sqrt(np.mean((p - y) ** 2))))
    assert s["mae"] == pytest.approx(float(np.mean(np.abs(p - y))))


# ------------------------------------------------------------------------------------------ persistence
def test_persistence_is_the_target_at_the_last_input_step():
    cols = ["a", TARGET_COLUMN, "b"]
    X = np.zeros((3, 4, 3))
    X[:, :, 1] = np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]])
    np.testing.assert_array_equal(FB.persistence_forecast(X, cols, TARGET_COLUMN), [4, 8, 12])


def test_persistence_needs_the_target_among_the_features():
    with pytest.raises(FB.InputError):
        FB.persistence_forecast(np.zeros((1, 2, 1)), ["a"], TARGET_COLUMN)


def test_persistence_on_a_ramp_is_off_by_exactly_horizon_times_slope():
    """Outlet rises 0.5 degC per step: 'now' is wrong by 6 steps x 0.5 = 3.0 degC for every window."""
    n = 200
    df = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=n, freq="5min")})
    for c in DEFAULT_FEATURE_COLUMNS:
        df[c] = 0.5 * np.arange(n)
    sp = DataPipeline().split_windows(df)
    pred = FB.persistence_forecast(sp.X_test, DEFAULT_FEATURE_COLUMNS, TARGET_COLUMN)
    s = FB.score(pred, sp.y_test)
    assert s["mae"] == pytest.approx(3.0) and s["rmse"] == pytest.approx(3.0)


# ------------------------------------------------------------------------------------------ seasonal naive
def test_seasonal_naive_looks_up_by_timestamp_and_is_nan_where_the_lag_is_missing():
    t = pd.date_range("2024-01-01", periods=10, freq="1h")
    df = pd.DataFrame({"timestamp": t, "v": np.arange(10, dtype=float) * 10}).drop(index=[3]).reset_index(drop=True)
    rows = np.array([4, 5, 8])  # frame rows: timestamps 05:00, 06:00, 09:00 (hour 3 is gone)
    out = FB.seasonal_naive_forecast(df, rows, "v", pd.Timedelta(hours=3))
    # 05:00-3h = 02:00 -> 20 ; 06:00-3h = 03:00 -> missing ; 09:00-3h = 06:00 -> 60
    assert out[0] == 20 and math.isnan(out[1]) and out[2] == 60


def test_seasonal_naive_needs_unique_timestamps_and_a_time_column():
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02"]), "v": [1.0, 2.0, 3.0]})
    with pytest.raises(FB.InputError, match="unique"):
        FB.seasonal_naive_forecast(df, np.array([2]), "v", pd.Timedelta(days=1))
    with pytest.raises(FB.InputError, match="timestamp"):
        FB.seasonal_naive_forecast(df.drop(columns=["timestamp"]), np.array([2]), "v", pd.Timedelta(days=1))


def test_train_mean_is_constant():
    out = FB.train_mean_forecast(np.array([1.0, 2.0, 6.0]), 4)
    assert out.tolist() == [3.0, 3.0, 3.0, 3.0]


# ------------------------------------------------------------------------------------------ the whole report
def test_a_perfectly_daily_series_is_forecast_exactly_by_the_seasonal_baseline_and_not_by_persistence(tmp_path):
    rep = FB.run(_write(tmp_path, _daily_frame(5)), model_dir=None, registry_path=None)
    assert rep["seasonal_naive"]["coverage_of_test_windows"] == 1.0
    assert rep["baselines_all_test_windows"]["seasonal_naive"]["rmse"] < 1e-4
    assert rep["baselines_all_test_windows"]["persistence"]["rmse"] > 0.1
    p, tm = rep["baselines_all_test_windows"]["persistence"], rep["baselines_all_test_windows"]["train_mean"]
    assert tm["rmse"] > p["rmse"]  # on a smooth series "now" beats a constant
    assert rep["protocol"]["test_windows"] == rep["baselines_all_test_windows"]["persistence"]["n"]


def test_the_common_subset_is_scored_for_every_method_on_the_same_windows(tmp_path):
    df = _daily_frame(5, drop=(900, 930))  # a 30-row hole inside the 24 h look-back of some test targets
    rep = FB.run(_write(tmp_path, df), model_dir=None, registry_path=None)
    common = rep["baselines_common_subset"]
    assert {c["n"] for c in common.values()} == {common["seasonal_naive"]["n"]}
    cov = rep["seasonal_naive"]["coverage_of_test_windows"]
    assert 0 < cov < 1
    # recompute the expected coverage independently
    frame = DataPipeline().load_csv(_write(tmp_path, df, "again.csv"))
    sp = DataPipeline().split_windows(frame)
    have = set(pd.DatetimeIndex(frame["timestamp"]))
    rows = sp.target_rows(sp.test_starts)
    lag = [frame["timestamp"].iloc[r] - pd.Timedelta(hours=24) in have for r in rows]
    assert cov == pytest.approx(float(np.mean(lag)))
    assert common["seasonal_naive"]["n"] == sum(lag)


def test_windows_across_a_data_gap_are_reported(tmp_path):
    rep = FB.run(_write(tmp_path, _daily_frame(5, drop=(1000, 1001))), model_dir=None, registry_path=None)
    a = rep["audit"]
    assert a["test_windows_with_a_time_gap"] + a["train_windows_with_a_time_gap"] == 17  # seq_len + horizon - 1 windows span one hole
    clean = FB.run(_write(tmp_path, _daily_frame(5), "clean.csv"), model_dir=None, registry_path=None)["audit"]
    assert clean["test_windows_with_a_time_gap"] == 0 and clean["train_windows_with_a_time_gap"] == 0


def test_boundary_overlap_is_reported_and_removed_by_the_purge_gap(tmp_path):
    path = _write(tmp_path, _daily_frame(5))
    legacy = FB.run(path, model_dir=None, registry_path=None)
    purged = FB.run(path, purge_gap=17, model_dir=None, registry_path=None)
    assert legacy["audit"]["boundary_overlap_rows"] == 17 and legacy["audit"]["rows_read_by_both_splits"] == 17
    assert purged["audit"]["boundary_overlap_rows"] == 0 and purged["audit"]["rows_read_by_both_splits"] == 0
    assert purged["protocol"]["split_id"].endswith(";purge_gap=17") and "purge_gap" not in legacy["protocol"]["split_id"]
    assert purged["protocol"]["test_windows"] == legacy["protocol"]["test_windows"] - 17


def test_anomaly_scope_counts_labelled_rows_removed_by_the_outlier_filter(tmp_path):
    df = _daily_frame(3)
    df["anomaly"] = 0
    for r in (400, 401):
        df.loc[r, "it_power_kw"] = 1e6  # extreme: removed by the filter
        df.loc[r, "anomaly"] = 1
    df.loc[600, "anomaly"] = 1  # labelled but not extreme: kept
    scope = FB.run(_write(tmp_path, df), model_dir=None, registry_path=None)["audit"]["anomaly_scope"]
    assert scope == {
        "rows_dropped_by_outlier_filter": 2,
        "anomaly_rows_in_file": 3,
        "anomaly_rows_removed_before_training": 2,
        "anomaly_rows_removed_share": pytest.approx(2 / 3),
    }
    assert FB.run(_write(tmp_path, _daily_frame(3), "plain.csv"), model_dir=None, registry_path=None)["audit"]["anomaly_scope"] is None


def test_the_report_is_deterministic(tmp_path):
    path = _write(tmp_path, _daily_frame(4))
    a = FB.run(path, model_dir=None, registry_path=None)
    b = FB.run(path, model_dir=None, registry_path=None)
    assert a == b


# ------------------------------------------------------------------------------------------ registry and model wiring
def _registry(tmp_path: Path, sha: str | None, metrics=None) -> Path:
    entry = {"name": "forecaster", "kind": "forecaster", "created_at_utc": "2026-01-01T00:00:00+00:00", "dataset_sha256": sha, "metrics": metrics}
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"registry_version": 2, "artifacts": [entry]}))
    return p


def test_the_csv_is_matched_against_the_hash_the_registry_recorded(tmp_path):
    path = _write(tmp_path, _daily_frame(3))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert FB.run(path, registry_path=_registry(tmp_path, sha))["data"]["matches_registry"] is True
    assert FB.run(path, registry_path=_registry(tmp_path, "0" * 64))["data"]["matches_registry"] is False
    none = FB.run(path, registry_path=_registry(tmp_path, None))["data"]
    assert none["matches_registry"] is None
    missing = FB.run(path, registry_path=tmp_path / "nope.json")["data"]
    assert missing["matches_registry"] is None and "not found" in missing["registry_note"]


def test_without_a_model_the_verdict_is_not_verified(tmp_path):
    rep = FB.run(_write(tmp_path, _daily_frame(3)), model_dir=None, registry_path=None)
    assert rep["model"]["status"] == "not_run"
    assert rep["comparison"]["model_beats_persistence"] is None
    assert rep["verdict"].startswith("NOT VERIFIED")


def test_a_missing_model_directory_is_reported_not_raised(tmp_path):
    rep = FB.run(_write(tmp_path, _daily_frame(3)), model_dir=tmp_path / "no_such_dir", registry_path=None)
    assert rep["model"]["status"] == "not_run" and rep["model"]["reason"]
    assert rep["verdict"].startswith("NOT VERIFIED")


class _FakeForecaster:
    """Stands in for ThermalForecaster: same ``evaluate`` contract, a chosen error level."""

    rmse, mae = 0.5, 0.4

    @classmethod
    def load(cls, path):
        return cls()

    def evaluate(self, X, y):
        return np.zeros(len(y)), self.rmse, self.mae


def _patch_model(monkeypatch, rmse, mae):
    import src.lstm_model as lm

    fake = type("F", (_FakeForecaster,), {"rmse": rmse, "mae": mae})
    monkeypatch.setattr(lm, "ThermalForecaster", fake)
    monkeypatch.setattr(DataPipeline, "load_scaler", lambda self, path: setattr(self, "_scaler", _Identity()))


class _Identity:
    def transform(self, a):
        return np.asarray(a, dtype=np.float32)


def test_the_model_branch_scores_on_the_held_out_windows_and_compares_with_persistence(tmp_path, monkeypatch):
    path = _write(tmp_path, _daily_frame(5))
    base = FB.run(path, registry_path=None)["baselines_all_test_windows"]["persistence"]
    _patch_model(monkeypatch, rmse=base["rmse"] * 0.5, mae=base["mae"] * 0.5)
    rep = FB.run(path, model_dir=tmp_path, registry_path=None)
    assert rep["model"]["status"] == "ok" and rep["model"]["n"] == rep["protocol"]["test_windows"]
    assert rep["comparison"]["model_beats_persistence"] is True
    assert rep["comparison"]["rmse_change_pct_vs_persistence"] == pytest.approx(-50.0)
    assert "beats persistence" in rep["verdict"] and "NOT the registered" not in rep["verdict"]
    assert "not shown to be the registered model's own held-out data" in rep["verdict"]  # no registry match was established


def test_a_model_that_is_worse_or_only_better_on_one_metric_does_not_beat_persistence(tmp_path, monkeypatch):
    path = _write(tmp_path, _daily_frame(5))
    p = FB.run(path, registry_path=None)["baselines_all_test_windows"]["persistence"]
    for rmse, mae in ((p["rmse"] * 2, p["mae"] * 2), (p["rmse"] * 0.5, p["mae"] * 2)):
        _patch_model(monkeypatch, rmse, mae)
        rep = FB.run(path, model_dir=tmp_path, registry_path=None)
        assert rep["comparison"]["model_beats_persistence"] is False
        assert "does NOT beat persistence" in rep["verdict"]


def test_rescoring_the_registered_model_is_compared_with_its_registry_metrics_only_on_the_registered_file(tmp_path, monkeypatch):
    path = _write(tmp_path, _daily_frame(5))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    _patch_model(monkeypatch, rmse=0.5231, mae=0.4206)
    same = FB.run(path, model_dir=tmp_path, registry_path=_registry(tmp_path, sha, {"rmse": 0.5231534, "mae": 0.4206323}))
    assert same["registered_model"]["model_rescored_matches_registry"] is True
    assert "on the file the registry recorded" in same["verdict"]
    drift = FB.run(path, model_dir=tmp_path, registry_path=_registry(tmp_path, sha, {"rmse": 0.9, "mae": 0.4206323}))
    assert drift["registered_model"]["model_rescored_matches_registry"] is False
    other = FB.run(path, model_dir=tmp_path, registry_path=_registry(tmp_path, "1" * 64, {"rmse": 0.5231534, "mae": 0.4206323}))
    assert other["registered_model"]["model_rescored_matches_registry"] is None  # different file: no claim
    purged = FB.run(path, purge_gap=17, model_dir=tmp_path, registry_path=_registry(tmp_path, sha, {"rmse": 0.5231534, "mae": 0.4206323}))
    assert purged["registered_model"]["model_rescored_matches_registry"] is None  # different test set: no claim


# ------------------------------------------------------------------------------------------ the command line
def test_cli_writes_the_report_and_exits_zero(tmp_path):
    out = tmp_path / "out" / "report.json"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = FB.main(["--csv", str(_write(tmp_path, _daily_frame(3))), "--registry", str(tmp_path / "none.json"), "--out", str(out)])
    assert code == 0 and out.exists()
    doc = json.loads(out.read_text())
    assert doc["protocol"]["horizon_steps"] == 6 and doc["model"]["status"] == "not_run"
    assert "persistence" in buf.getvalue() and "verdict" in buf.getvalue()


def test_cli_auto_purge_gap_uses_seq_len_plus_horizon_minus_one(tmp_path):
    out = tmp_path / "r.json"
    with contextlib.redirect_stdout(io.StringIO()):
        FB.main(["--csv", str(_write(tmp_path, _daily_frame(3))), "--purge-gap", "auto", "--registry", str(tmp_path / "x"), "--out", str(out)])
    assert json.loads(out.read_text())["protocol"]["purge_gap"] == 17


@pytest.mark.parametrize("argv", [["--csv", "does_not_exist.csv"], ["--purge-gap", "-3"], ["--purge-gap", "many"], ["--season-hours", "0"]])
def test_cli_refuses_bad_input_with_status_2_and_writes_nothing(tmp_path, argv):
    csv_path = _write(tmp_path, _daily_frame(3))
    full = (["--csv", str(csv_path)] if "--csv" not in argv else []) + argv + ["--out", str(tmp_path / "never.json")]
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = FB.main(full)
    assert code == 2 and err.getvalue().startswith("error:")
    assert not (tmp_path / "never.json").exists()


# ------------------------------------------------------------------------------------------ outlier-filter dependence
def _regime_shift_frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    train = rng.normal(0.0, 1.0, 80)
    train[40] = 3.5 * train.std()  # outside 3 sigma of the train block alone
    test = rng.normal(20.0, 2.0, 20)  # a different regime afterwards, far outside the train block (about 14 to 26)
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"), "x": np.concatenate([train, test])})


def test_outlier_filter_audit_counts_decisions_that_depend_on_test_rows():
    a = FB.outlier_filter_audit(_regime_shift_frame(), ["x"], 3.0, 0.8)
    assert a["train_rows_with_a_different_decision"] >= 1  # the planted 3.5-sigma row: dropped alone, kept with the test rows
    assert a["rows_with_a_different_decision"] >= a["train_rows_with_a_different_decision"]
    assert a["test_rows_dropped_with_train_only_thresholds"] == 20  # every test row is far outside the train block
    assert a["test_rows_dropped_with_whole_file_thresholds"] < 20


def test_outlier_filter_audit_mirrors_the_pipeline_and_needs_a_time_column(tmp_path):
    df = _regime_shift_frame()
    path = _write(tmp_path, df)
    kept = len(DataPipeline(feature_columns=["x"], target_column="x", outlier_std=3.0).load_csv(path))
    assert kept == int(FB._keep_mask(df, df, ["x"], 3.0).sum())  # the audit applies the very rule load_csv applies
    assert FB.outlier_filter_audit(df.drop(columns=["timestamp"]), ["x"], 3.0, 0.8) is None
    unsorted = df.iloc[::-1].reset_index(drop=True)
    assert FB.outlier_filter_audit(unsorted, ["x"], 3.0, 0.8) == FB.outlier_filter_audit(df, ["x"], 3.0, 0.8)


def test_the_report_carries_the_outlier_dependence_block(tmp_path):
    rep = FB.run(_write(tmp_path, _daily_frame(3)), model_dir=None, registry_path=None)
    assert rep["audit"]["outlier_filter_dependence_on_test_rows"]["rows_with_a_different_decision"] == 0  # smooth data: no outliers
