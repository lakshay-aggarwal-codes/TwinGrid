"""
Tests for DataPipeline in src/lstm_model.py.

The real API is small: load_csv() (load + fill nulls + drop 3-sigma outliers),
prepare() (sliding windows, chronological train/test split, scaler fit on
train only), plus scaler save/load and transform_sequence(). Everything else
(seq_len, horizon, ...) is private state -- tests check it through behaviour
(output shapes), not by reaching into attributes.

Note prepare() returns (X_train, y_train, X_test, y_test) -- targets are
interleaved with features per split, not (X_train, X_test, y_train, y_test).
"""

import numpy as np
import pandas as pd
import pytest

from src.lstm_model import DEFAULT_FEATURE_COLUMNS, TARGET_COLUMN, DataPipeline


def _frame(n: int = 200, seed: int = 0) -> pd.DataFrame:
    """Small deterministic frame with every default feature column."""
    rng = np.random.default_rng(seed)
    data = {"timestamp": pd.date_range("2024-01-01", periods=n, freq="5min")}
    for i, col in enumerate(DEFAULT_FEATURE_COLUMNS):
        data[col] = 10.0 * (i + 1) + rng.normal(0, 1.0, n)
    return pd.DataFrame(data)


class TestInit:
    def test_defaults(self):
        pipe = DataPipeline()
        assert pipe.feature_columns == DEFAULT_FEATURE_COLUMNS
        assert pipe.scaler is None

    def test_default_feature_columns_are_not_shared_state(self):
        """Mutating one pipeline's feature list must not leak into another
        (the constructor copies DEFAULT_FEATURE_COLUMNS)."""
        a, b = DataPipeline(), DataPipeline()
        a.feature_columns.append("junk")
        assert "junk" not in b.feature_columns
        assert "junk" not in DEFAULT_FEATURE_COLUMNS

    def test_custom_feature_columns(self):
        cols = ["server_utilisation", "outside_temp_C"]
        assert DataPipeline(feature_columns=cols).feature_columns == cols


class TestLoadCsv:
    def test_loads_and_stores_dataframe(self, data_pipeline, sample_csv_file):
        df = data_pipeline.load_csv(sample_csv_file)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert all(c in df.columns for c in data_pipeline.feature_columns)
        assert TARGET_COLUMN in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])

    def test_missing_file_raises(self, data_pipeline):
        with pytest.raises(FileNotFoundError):
            data_pipeline.load_csv("non_existent_file.csv")

    def test_sorts_by_timestamp(self, data_pipeline, temp_data_dir):
        df = _frame(100).iloc[::-1]  # reversed
        path = temp_data_dir / "reversed.csv"
        df.to_csv(path, index=False)
        loaded = data_pipeline.load_csv(path)
        assert loaded["timestamp"].is_monotonic_increasing

    def test_fills_nulls(self, data_pipeline, temp_data_dir):
        df = _frame(100)
        df.loc[10:14, "server_utilisation"] = np.nan
        path = temp_data_dir / "nulls.csv"
        df.to_csv(path, index=False)
        loaded = data_pipeline.load_csv(path)
        assert not loaded[data_pipeline.feature_columns].isnull().any().any()

    def test_removes_extreme_outlier_rows(self, data_pipeline, temp_data_dir):
        df = _frame(200)
        df.loc[100, "it_power_kw"] = 1e6  # far beyond 3 sigma
        path = temp_data_dir / "outlier.csv"
        df.to_csv(path, index=False)
        loaded = data_pipeline.load_csv(path)
        # The planted row is gone...
        assert loaded["it_power_kw"].max() < 1e5
        # ...but the filter isn't wiping data: even clean Gaussian noise loses a
        # few rows across 10 columns at +/-3 sigma (~3% here), so allow that,
        # not an exact count.
        assert 0.9 * len(df) < len(loaded) < len(df)

    def test_missing_feature_columns_do_not_fail_at_load(self, data_pipeline, temp_data_dir):
        """load_csv only outlier-checks columns that exist; a CSV missing
        feature columns loads fine and the problem surfaces in prepare()."""
        df = _frame(100)[["timestamp", "server_utilisation"]]
        path = temp_data_dir / "incomplete.csv"
        df.to_csv(path, index=False)
        loaded = data_pipeline.load_csv(path)
        assert len(loaded) == 100
        with pytest.raises(ValueError, match="Missing columns"):
            data_pipeline.prepare()


class TestPrepare:
    def test_returns_four_arrays_in_documented_order(self, data_pipeline, sample_sensor_data):
        out = data_pipeline.prepare(sample_sensor_data)
        assert len(out) == 4
        X_train, y_train, X_test, y_test = out
        assert all(isinstance(a, np.ndarray) for a in out)
        assert X_train.ndim == 3 and X_test.ndim == 3
        assert y_train.ndim == 1 and y_test.ndim == 1
        assert len(X_train) == len(y_train)
        assert len(X_test) == len(y_test)

    def test_shapes_and_split_sizes(self, data_pipeline, sample_sensor_data):
        X_train, y_train, X_test, y_test = data_pipeline.prepare(sample_sensor_data)
        n_feat = len(data_pipeline.feature_columns)
        assert X_train.shape[1:] == (12, n_feat)
        assert X_test.shape[1:] == (12, n_feat)

        n = len(sample_sensor_data) - 12 - 6 + 1  # seq_len=12, horizon=6
        assert len(X_train) == int(n * 0.8)
        assert len(X_train) + len(X_test) == n

    def test_custom_seq_len_horizon_features_reflected_in_shapes(self):
        cols = ["server_utilisation", "outside_temp_C"]
        pipe = DataPipeline(seq_len=6, horizon=3, train_ratio=0.5, feature_columns=cols)
        X_train, y_train, X_test, y_test = pipe.prepare(_frame(100))
        n = 100 - 6 - 3 + 1
        assert X_train.shape == (int(n * 0.5), 6, 2)
        assert len(X_train) + len(X_test) == n

    def test_split_is_chronological_and_targets_are_raw(self, data_pipeline):
        """Targets are the value `horizon` steps after each window, in time
        order (train first, then test), and are NOT scaled."""
        df = _frame(150)
        _, y_train, _, y_test = data_pipeline.prepare(df)
        expected = df[TARGET_COLUMN].values[12 + 6 - 1 :].astype(np.float32)
        np.testing.assert_array_equal(np.concatenate([y_train, y_test]), expected)

    def test_scaler_fit_on_train_only(self, data_pipeline, sample_sensor_data):
        X_train, _, X_test, _ = data_pipeline.prepare(sample_sensor_data)
        assert data_pipeline.scaler is not None
        # One scaler row per (window, timestep) of the TRAIN split only.
        assert data_pipeline.scaler.n_samples_seen_ == X_train.shape[0] * X_train.shape[1]
        # Train features land in [0, 1]; test is transformed (not clipped),
        # so it may legitimately fall outside that range.
        assert X_train.min() >= -1e-6
        assert X_train.max() <= 1 + 1e-6

    def test_deterministic(self, sample_sensor_data):
        a = DataPipeline().prepare(sample_sensor_data)
        b = DataPipeline().prepare(sample_sensor_data)
        for x, y in zip(a, b):
            np.testing.assert_array_equal(x, y)

    def test_uses_loaded_data_when_no_df_given(self, data_pipeline, sample_csv_file):
        data_pipeline.load_csv(sample_csv_file)
        X_train, y_train, X_test, y_test = data_pipeline.prepare()
        assert len(X_train) > 0 and len(X_test) > 0

    def test_no_data_loaded_raises(self, data_pipeline):
        with pytest.raises(ValueError, match="No data loaded"):
            data_pipeline.prepare()

    def test_missing_feature_column_raises(self, data_pipeline, sample_sensor_data):
        with pytest.raises(ValueError, match="Missing columns"):
            data_pipeline.prepare(sample_sensor_data.drop(columns=["server_utilisation"]))

    def test_missing_target_column_raises(self):
        # Target is separate from features: drop it from a frame whose
        # features are otherwise complete (server_outlet_temp_C is both, in
        # the defaults, so use a pipeline with a distinct target).
        pipe = DataPipeline(feature_columns=["server_utilisation"], target_column="pue")
        df = _frame(100).drop(columns=["pue"])
        with pytest.raises(ValueError, match="Missing columns"):
            pipe.prepare(df)

    def test_not_enough_data_raises(self, data_pipeline):
        with pytest.raises(ValueError, match="Not enough data"):
            data_pipeline.prepare(_frame(12 + 6 - 1))  # one row short of a single window


class TestScalerHelpers:
    def test_save_scaler_before_prepare_raises(self, data_pipeline, temp_data_dir):
        with pytest.raises(ValueError, match="Scaler not fitted"):
            data_pipeline.save_scaler(temp_data_dir / "scaler.joblib")

    def test_transform_sequence_before_prepare_raises(self, data_pipeline):
        with pytest.raises(ValueError, match="Scaler not fitted"):
            data_pipeline.transform_sequence(np.zeros((12, 10)))

    def test_transform_sequence_preserves_shape_and_matches_training_scale(self, data_pipeline, sample_sensor_data):
        data_pipeline.prepare(sample_sensor_data)
        raw = sample_sensor_data[data_pipeline.feature_columns].values[:12].astype(np.float32)

        scaled_2d = data_pipeline.transform_sequence(raw)
        scaled_3d = data_pipeline.transform_sequence(raw[np.newaxis])
        assert scaled_2d.shape == (12, 10)
        assert scaled_3d.shape == (1, 12, 10)
        np.testing.assert_allclose(scaled_2d, scaled_3d[0], rtol=1e-6)

    def test_scaler_save_load_roundtrip(self, data_pipeline, sample_sensor_data, temp_data_dir):
        data_pipeline.prepare(sample_sensor_data)
        path = temp_data_dir / "scaler.joblib"
        data_pipeline.save_scaler(path)
        assert path.exists()

        fresh = DataPipeline()
        fresh.load_scaler(path)
        raw = sample_sensor_data[fresh.feature_columns].values[:12].astype(np.float32)
        np.testing.assert_allclose(fresh.transform_sequence(raw), data_pipeline.transform_sequence(raw), rtol=1e-6)
