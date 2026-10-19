"""Task 11: leakage audit of the thermal forecaster's data pipeline (``src.lstm_model.DataPipeline``).

Each test states which audit claim it settles. Confirmed defects are recorded as ``xfail(strict=True)`` so the suite stays
green but a future fix cannot go unnoticed (the strict xfail turns into a failure that says "remove the marker"). Nothing
here trains a model, needs TensorFlow, or reads data that is not built in the test.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.lstm_model import DEFAULT_FEATURE_COLUMNS, TARGET_COLUMN, DataPipeline

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("forecast_baselines_under_test", ROOT / "scripts" / "forecast_baselines.py")
FB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FB)

SEQ, HOR = 12, 6
GAP = SEQ + HOR - 1


def _frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    """Every default feature column, 5-minute timestamps, and no two rows alike (a trend plus noise per column)."""
    rng = np.random.default_rng(seed)
    data = {"timestamp": pd.date_range("2024-01-01", periods=n, freq="5min")}
    for i, col in enumerate(DEFAULT_FEATURE_COLUMNS):
        data[col] = 10.0 * (i + 1) + 0.01 * np.arange(n) + rng.normal(0, 1.0, n)
    return pd.DataFrame(data)


def _csv(tmp_path: Path, df: pd.DataFrame, name: str = "d.csv") -> Path:
    path = tmp_path / name
    df.to_csv(path, index=False)
    return path


# ------------------------------------------------------------------------------------------ the split boundary
@pytest.mark.parametrize("seq,hor", [(12, 6), (6, 3), (24, 12), (1, 1)])
def test_legacy_split_overlaps_by_seq_len_plus_horizon_minus_one(seq, hor):
    """CONFIRMED: windows are built over the whole frame and split by position, so the first test windows read rows that
    the last train windows read (as inputs) or train on (as targets). This pins the current, legacy behaviour."""
    pipe = DataPipeline(seq_len=seq, horizon=hor)
    split = pipe.split_windows(_frame(400))
    assert split.boundary_overlap_rows() == seq + hor - 1
    shared = split.rows_touched(split.train_starts) & split.rows_touched(split.test_starts)
    assert len(shared) == seq + hor - 1


@pytest.mark.xfail(strict=True, reason="CONFIRMED defect TG-T11-1: default split has no purge gap; 17 rows are read by both splits")
def test_default_split_boundaries_are_strictly_ordered():
    split = DataPipeline().split_windows(_frame(400))
    assert split.boundary_overlap_rows() == 0
    assert not (split.rows_touched(split.train_starts) & split.rows_touched(split.test_starts))


@pytest.mark.parametrize("seq,hor", [(12, 6), (6, 3), (24, 12), (1, 1)])
def test_purged_split_boundaries_are_strictly_ordered(seq, hor):
    """With ``purge_gap = seq_len + horizon - 1`` no row is read by both splits, and time order holds throughout."""
    df = _frame(400)
    pipe = DataPipeline(seq_len=seq, horizon=hor)
    pipe = DataPipeline(seq_len=seq, horizon=hor, purge_gap=pipe.recommended_purge_gap)
    split = pipe.split_windows(df)
    assert split.boundary_overlap_rows() == 0
    train_rows = split.rows_touched(split.train_starts)
    test_rows = split.rows_touched(split.test_starts)
    assert not (train_rows & test_rows)
    assert max(train_rows) < min(test_rows)
    assert split.target_rows(split.train_starts).max() < split.test_starts.min()
    assert np.all(np.diff(split.train_starts) == 1) and np.all(np.diff(split.test_starts) == 1)
    n = len(df) - seq - hor + 1
    assert len(split.y_train) + len(split.y_test) == n - pipe.recommended_purge_gap  # exactly the purged windows are lost


def test_targets_are_the_frame_values_at_the_documented_horizon():
    df = _frame(300)
    pipe = DataPipeline(purge_gap=GAP)
    split = pipe.split_windows(df)
    target = df[TARGET_COLUMN].to_numpy(dtype=np.float32)
    np.testing.assert_array_equal(split.y_train, target[split.target_rows(split.train_starts)])
    np.testing.assert_array_equal(split.y_test, target[split.target_rows(split.test_starts)])
    first = split.X_train[0]
    np.testing.assert_array_equal(first, df[DEFAULT_FEATURE_COLUMNS].to_numpy(dtype=np.float32)[0:SEQ])


@pytest.mark.parametrize("bad", [-1, 1.5, "17", True, None])
def test_purge_gap_must_be_a_whole_number_of_windows(bad):
    with pytest.raises(ValueError):
        DataPipeline(purge_gap=bad)


def test_a_gap_that_leaves_no_test_windows_is_refused():
    df = _frame(60)
    with pytest.raises(ValueError, match="no test windows"):
        DataPipeline(purge_gap=1000).split_windows(df)


def test_split_id_records_the_purge_only_when_there_is_one():
    reg = json.loads((ROOT / "models" / "registry.json").read_text(encoding="utf-8"))
    registered = next(a for a in reg["artifacts"] if a["name"] == "forecaster")["split_id"]
    assert DataPipeline(seq_len=12, horizon=6, train_ratio=0.8).split_id() == registered  # the legacy label is unchanged
    assert DataPipeline(train_ratio=0.8, purge_gap=17).split_id() == registered + ";purge_gap=17"


def test_prepare_is_the_scaled_split_windows():
    """Guards the refactor: ``prepare`` still returns exactly the scaled ``split_windows`` (scaler fit on train windows)."""
    from sklearn.preprocessing import MinMaxScaler

    df = _frame(300)
    for gap in (0, GAP):
        pipe = DataPipeline(purge_gap=gap)
        Xtr, ytr, Xte, yte = pipe.prepare(df)
        sp = DataPipeline(purge_gap=gap).split_windows(df)
        sc = MinMaxScaler().fit(sp.X_train.reshape(-1, sp.X_train.shape[-1]))
        np.testing.assert_allclose(Xtr, sc.transform(sp.X_train.reshape(-1, 10)).reshape(sp.X_train.shape), rtol=0, atol=0)
        np.testing.assert_allclose(Xte, sc.transform(sp.X_test.reshape(-1, 10)).reshape(sp.X_test.shape), rtol=0, atol=0)
        np.testing.assert_array_equal(ytr, sp.y_train)
        np.testing.assert_array_equal(yte, sp.y_test)


# ------------------------------------------------------------------------------------------ the scaler
@pytest.mark.parametrize("gap", [0, GAP])
def test_scaler_is_fit_on_train_windows_only(gap):
    """REFUTED (for the claim "scaler fit on all data"): a spike far into the test period never reaches the scaler."""
    df = _frame(400)
    df.loc[390, "it_power_kw"] = 1e5  # row 390 lies well after the train/test boundary (about row 320)
    pipe = DataPipeline(purge_gap=gap)
    _, _, X_test, _ = pipe.prepare(df)
    sp = DataPipeline(purge_gap=gap).split_windows(df)
    col = DEFAULT_FEATURE_COLUMNS.index("it_power_kw")
    assert pipe.scaler.data_max_[col] == sp.X_train[:, :, col].max() < 1e4
    assert X_test[:, :, col].max() > 1  # the test windows are transformed, not clipped, so the spike is visible there
    assert pipe.scaler.n_samples_seen_ == sp.X_train.shape[0] * SEQ


# ------------------------------------------------------------------------------------------ duplicates
def test_no_identical_windows_in_both_splits_and_the_check_can_fail():
    df = _frame(400)
    sp = DataPipeline().split_windows(df)
    assert FB.count_shared_windows(sp.X_train, sp.X_test) == 0
    # prove the detector is not vacuous: repeat a training block verbatim inside the test period
    dup = df.copy()
    block = dup.iloc[40:80][DEFAULT_FEATURE_COLUMNS].to_numpy()
    dup.iloc[340:380, dup.columns.get_indexer(DEFAULT_FEATURE_COLUMNS)] = block
    sp2 = DataPipeline().split_windows(dup)
    assert FB.count_shared_windows(sp2.X_train, sp2.X_test) > 0


# ------------------------------------------------------------------------------------------ loading and ordering
def test_unsorted_input_is_ordered_by_time_before_windowing(tmp_path):
    df = _frame(120).iloc[::-1]
    loaded = DataPipeline().load_csv(_csv(tmp_path, df))
    assert loaded["timestamp"].is_monotonic_increasing
    assert loaded["timestamp"].is_unique


def test_forward_fill_never_uses_a_later_value_in_the_middle_of_the_series(tmp_path):
    """REFUTED (for "bfill leaks the future"): after ffill the only NaN left is a leading one, so backward fill can only
    touch rows at the very start of the series. A gap in the middle takes the PREVIOUS value, not the next."""
    df = _frame(100)
    df.loc[40:44, "humidity_pct"] = np.nan
    df.loc[0:1, "pue"] = np.nan
    df.loc[98:99, "water_flow_lpm"] = np.nan
    path = _csv(tmp_path, df)
    written = pd.read_csv(path)  # what is actually on disk (CSV floats are rounded to 16 digits)
    loaded = DataPipeline(outlier_std=1e9).load_csv(path)
    assert (loaded.loc[40:44, "humidity_pct"] == written["humidity_pct"].iloc[39]).all()
    assert (loaded.loc[98:99, "water_flow_lpm"] == written["water_flow_lpm"].iloc[97]).all()
    assert (loaded.loc[0:1, "pue"] == written["pue"].iloc[2]).all()  # the one place a later value is used: the first rows


@pytest.mark.xfail(strict=True, reason="CONFIRMED gap TG-T11-2: load_csv accepts duplicate timestamps")
def test_duplicate_timestamps_are_rejected_at_load(tmp_path):
    df = _frame(100)
    df.loc[50, "timestamp"] = df.loc[49, "timestamp"]
    with pytest.raises(ValueError):
        DataPipeline().load_csv(_csv(tmp_path, df))


# ------------------------------------------------------------------------------------------ the outlier filter
def _one_feature_frame(values: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=len(values), freq="5min"), "x": values})


@pytest.mark.xfail(strict=True, reason="CONFIRMED defect TG-T11-3: outlier thresholds are computed on the WHOLE file, test rows included")
def test_outlier_decisions_for_train_rows_do_not_depend_on_test_rows(tmp_path):
    rng = np.random.default_rng(1)
    train = rng.normal(0.0, 1.0, 800)
    train[400] = 3.5 * train.std()  # just outside 3 sigma of the train block alone
    test = rng.normal(8.0, 6.0, 200)  # a very different regime afterwards, which inflates the whole-file sigma
    pipe = DataPipeline(feature_columns=["x"], target_column="x", outlier_std=3.0)
    alone = pipe.load_csv(_csv(tmp_path, _one_feature_frame(train), "a.csv"))
    together = pipe.load_csv(_csv(tmp_path, _one_feature_frame(np.concatenate([train, test])), "b.csv"))
    kept_alone = set(alone["timestamp"])
    kept_together = set(together["timestamp"]) & set(_one_feature_frame(train)["timestamp"])
    assert kept_alone == kept_together


@pytest.mark.xfail(strict=True, reason="CONFIRMED defect TG-T11-4: rows dropped by the outlier filter are not time-contiguous windows any more")
def test_windows_are_time_contiguous_after_outlier_removal(tmp_path):
    df = _frame(300)
    df.loc[150, "it_power_kw"] = 1e6  # dropped by the 3-sigma filter
    pipe = DataPipeline()
    frame = pipe.load_csv(_csv(tmp_path, df))
    split = pipe.split_windows(frame)
    gaps = FB.window_time_gaps(frame, np.concatenate([split.train_starts, split.test_starts]), SEQ, HOR, 300.0)
    assert gaps == 0


def test_the_time_gap_counter_counts_exactly_the_windows_that_span_a_dropped_row(tmp_path):
    """The measuring tool behind the previous test: one dropped row makes ``seq_len + horizon - 1`` windows non-contiguous."""
    df = _frame(300)
    df.loc[150, "it_power_kw"] = 1e6
    pipe = DataPipeline()
    frame = pipe.load_csv(_csv(tmp_path, df))
    assert len(frame) == 299 or len(frame) < 300
    split = pipe.split_windows(frame)
    gaps = FB.window_time_gaps(frame, np.concatenate([split.train_starts, split.test_starts]), SEQ, HOR, 300.0)
    dropped = 300 - len(frame)
    assert dropped >= 1 and 1 <= gaps <= dropped * GAP


# ------------------------------------------------------------------------------------------ the training code path
def test_no_random_split_of_the_time_series_in_the_forecaster_path():
    """REFUTED (for "random splits of the time series"): neither the pipeline nor the training script uses a shuffled or
    k-fold split. (Keras ``validation_split`` takes the LAST fraction of the already time-ordered training arrays.)"""
    forbidden = re.compile(r"train_test_split|shuffle\s*=\s*True|KFold|ShuffleSplit|random_split|StratifiedKFold")
    for rel in ("src/lstm_model.py", "notebooks/train_all.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{rel} uses a randomised split"
    assert "validation_split=validation_split" in (ROOT / "src/lstm_model.py").read_text(encoding="utf-8")
