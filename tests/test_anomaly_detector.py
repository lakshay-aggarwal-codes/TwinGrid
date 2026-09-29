"""
Tests for AnomalyDetector in src/anomaly_detector.py.

The detector works on 5 features (FEATURE_COLUMNS: water_flow_lpm,
water_pressure_bar, server_outlet_temp_C, it_power_kw, humidity_pct) -- every
DataFrame passed to it needs all five, plus an 'anomaly' column for training
(normal rows only) and evaluation.

Real API, for reference: detect() returns a TUPLE (error_scores, alerts);
evaluate() returns precision/recall/f1/confusion_matrix; save()/load() work on
a DIRECTORY (model.keras + scaler.joblib + config.json) and load() is a
classmethod. Most internal state is private (_seq_len, _percentile, ...);
only `threshold` is a public property.
"""

import json

import numpy as np
import pandas as pd
import pytest

from src.anomaly_detector import FEATURE_COLUMNS, AnomalyDetector, NotTrainedError, ShapeError


def _synthetic_df(n: int = 300, seed: int = 42, anomaly_idx: tuple[int, ...] = ()) -> pd.DataFrame:
    """Smooth sensor data for the 5 detector features. Rows in anomaly_idx get
    a large, obvious spike and anomaly=1; everything else is normal."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 4 * np.pi, n)
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min"),
            "water_flow_lpm": 40 + 10 * np.sin(t) + rng.normal(0, 2, n),
            "water_pressure_bar": 3 + 0.5 * np.sin(t) + rng.normal(0, 0.1, n),
            "server_outlet_temp_C": 30 + 5 * np.sin(t) + rng.normal(0, 1, n),
            "it_power_kw": 300 + 100 * np.sin(t) + rng.normal(0, 10, n),
            "humidity_pct": 50 + 10 * np.sin(t) + rng.normal(0, 2, n),
            "anomaly": np.zeros(n),
        }
    )
    for i in anomaly_idx:
        df.loc[i, "server_outlet_temp_C"] += 15
        df.loc[i, "water_flow_lpm"] *= 2.0
        df.loc[i, "water_pressure_bar"] *= 0.5
        df.loc[i, "anomaly"] = 1
    return df


@pytest.fixture(scope="module")
def trained():
    """One trained detector shared by tests that only need a fitted model
    (training dominates this file's runtime, so don't repeat it per test)."""
    detector = AnomalyDetector(verbose=0)
    detector.train(_synthetic_df(600), epochs=8, batch_size=32)
    return detector


class TestAnomalyDetector:
    """Test suite for AnomalyDetector class."""

    # ---- construction -------------------------------------------------

    def test_init_default_params(self):
        detector = AnomalyDetector()

        assert detector._seq_len == 12
        assert detector._percentile == 95
        assert detector._feature_columns == FEATURE_COLUMNS
        assert detector._model is None
        assert detector._scaler is None
        assert detector._threshold is None
        assert detector.threshold is None
        assert detector._is_trained is False

    def test_init_custom_params(self):
        detector = AnomalyDetector(seq_len=10, percentile=99, verbose=0)

        assert detector._seq_len == 10
        assert detector._percentile == 99
        assert detector._verbose == 0

    def test_build_model(self, anomaly_detector):
        """Test model building."""
        model = anomaly_detector._build_model()

        assert model is not None
        assert hasattr(model, "input_shape")
        assert hasattr(model, "output_shape")

    # ---- data preparation (no training needed) ------------------------

    def test_prepare_data_normal_only(self, anomaly_detector, sample_sensor_data):
        normal_data = sample_sensor_data[sample_sensor_data["anomaly"] == 0].copy()

        sequences, labels = anomaly_detector._prepare_data(normal_data, normal_only=True)

        assert sequences.shape[0] > 0
        assert sequences.shape[1] == anomaly_detector._seq_len
        assert sequences.shape[2] == len(FEATURE_COLUMNS)  # 5 detector features
        assert labels.shape[0] == sequences.shape[0]
        assert np.all(labels == 0)  # All should be normal

    def test_prepare_data_with_anomalies(self, anomaly_detector, sample_sensor_data):
        """Test data preparation with anomalies included."""
        sequences, labels = anomaly_detector._prepare_data(sample_sensor_data, normal_only=False)

        assert sequences.shape[0] > 0
        assert labels.shape[0] == sequences.shape[0]

        # Should have some anomalies
        assert np.sum(labels) > 0
        assert np.sum(labels) < len(labels)  # Not all should be anomalies

    def test_window_is_labelled_anomalous_iff_it_contains_an_anomalous_row(self, anomaly_detector):
        df = _synthetic_df(60, anomaly_idx=(30,))
        _, labels = anomaly_detector._prepare_data(df, normal_only=False)

        # Windows starting at 19..30 (12 rows each) include row 30.
        expected = np.zeros(60 - 12 + 1, dtype=np.int32)
        expected[30 - 12 + 1 : 30 + 1] = 1
        np.testing.assert_array_equal(labels, expected)

    def test_prepare_data_missing_feature_column_raises(self, anomaly_detector):
        df = _synthetic_df(50).drop(columns=["water_pressure_bar"])
        with pytest.raises(ValueError, match="Missing columns"):
            anomaly_detector._prepare_data(df)

    @pytest.mark.parametrize("n_rows,expected", [(5, 0), (11, 0), (12, 1), (15, 4)])
    def test_sequence_count_is_rows_minus_seq_len_plus_one(self, anomaly_detector, n_rows, expected):
        sequences, _ = anomaly_detector._prepare_data(_synthetic_df(n_rows), normal_only=True)
        assert sequences.shape[0] == expected

    def test_sequences_from_df_matches_prepare_data(self, anomaly_detector):
        df = _synthetic_df(50)
        via_public = anomaly_detector.sequences_from_df(df)
        via_private, _ = anomaly_detector._prepare_data(df, normal_only=False)
        np.testing.assert_array_equal(via_public, via_private)

    # ---- training -----------------------------------------------------

    def test_train_basic(self, anomaly_detector, sample_sensor_data):
        """Test basic training functionality."""
        history = anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)

        assert anomaly_detector._is_trained is True
        assert anomaly_detector._model is not None
        assert anomaly_detector._scaler is not None
        assert anomaly_detector._threshold is not None
        assert anomaly_detector._threshold > 0

        # Check history
        assert isinstance(history, dict)
        assert "loss" in history
        assert "val_loss" in history
        assert len(history["loss"]) > 0

    def test_train_custom_params(self, anomaly_detector, sample_sensor_data):
        """Test training with custom parameters."""
        history = anomaly_detector.train(sample_sensor_data, epochs=3, batch_size=8, validation_split=0.3, patience=5)

        assert anomaly_detector._is_trained is True
        assert len(history["loss"]) <= 3  # Should stop at or before 3 epochs

    def test_train_no_normal_data_raises(self, anomaly_detector):
        """Every row labelled anomalous -> nothing to train on. (All 5 feature
        columns must be present or the missing-columns check fires first.)"""
        df = _synthetic_df(100)
        df["anomaly"] = 1.0

        with pytest.raises(ValueError, match="No normal sequences found"):
            anomaly_detector.train(df)
        assert anomaly_detector._is_trained is False

    def test_train_with_fewer_rows_than_seq_len_raises(self, anomaly_detector):
        """Insufficient data means fewer rows than one window (seq_len=12);
        20 rows would still yield 9 valid windows."""
        with pytest.raises(ValueError, match="No normal sequences found"):
            anomaly_detector.train(_synthetic_df(8))

    def test_train_missing_feature_column_raises(self, anomaly_detector):
        df = _synthetic_df(100).drop(columns=["water_pressure_bar"])
        with pytest.raises(ValueError, match="Missing columns"):
            anomaly_detector.train(df)

    # ---- detection ----------------------------------------------------

    def test_detect_before_training_raises(self, anomaly_detector):
        sequences = anomaly_detector.sequences_from_df(_synthetic_df(50))
        with pytest.raises(NotTrainedError, match="trained before detection"):
            anomaly_detector.detect(sequences)

    def test_detect_returns_scores_and_alerts(self, trained):
        sequences = trained.sequences_from_df(_synthetic_df(100, seed=7))

        errors, alerts = trained.detect(sequences)  # a (scores, alerts) TUPLE

        assert isinstance(errors, np.ndarray) and isinstance(alerts, np.ndarray)
        assert len(errors) == len(alerts) == len(sequences)
        assert alerts.dtype == bool
        assert np.all(errors >= 0)

    def test_detect_rejects_wrong_shape(self, trained):
        with pytest.raises(ShapeError):
            trained.detect(np.zeros((5, 12, 4), dtype=np.float32))  # 4 features, not 5
        with pytest.raises(ShapeError):
            trained.detect(np.zeros((5, 10, 5), dtype=np.float32))  # seq_len 10, not 12

    def test_detect_threshold_override(self, trained):
        sequences = trained.sequences_from_df(_synthetic_df(100, seed=7))

        _, none_flagged = trained.detect(sequences, threshold=float("inf"))
        _, all_flagged = trained.detect(sequences, threshold=-1.0)

        assert not none_flagged.any()
        assert all_flagged.all()

    def test_injected_anomalies_score_higher_than_clean_windows(self, trained):
        """Windows containing a large planted spike should reconstruct worse
        than clean ones. Compares scores rather than asserting on alert counts,
        since the 95th-percentile threshold flags ~5% of normal windows anyway."""
        df = _synthetic_df(200, seed=11, anomaly_idx=(50, 100, 150))
        sequences, labels = trained._prepare_data(df, normal_only=False)

        errors, _ = trained.detect(sequences)

        assert labels.sum() > 0 and (labels == 0).sum() > 0
        assert errors[labels == 1].mean() > errors[labels == 0].mean()

    def test_compute_errors(self, anomaly_detector, sample_sensor_data):
        """Test reconstruction error computation."""
        anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)

        sequences, _ = anomaly_detector._prepare_data(sample_sensor_data, normal_only=False)
        errors = anomaly_detector._compute_errors(sequences)

        assert len(errors) == len(sequences)
        assert all(error >= 0 for error in errors)
        assert isinstance(errors, np.ndarray)

    # ---- evaluation ---------------------------------------------------

    def test_evaluate_before_training_raises(self, anomaly_detector, sample_sensor_data):
        with pytest.raises(NotTrainedError, match="trained before evaluation"):
            anomaly_detector.evaluate(sample_sensor_data)

    def test_evaluate_returns_documented_metrics(self, trained):
        df = _synthetic_df(150, seed=3, anomaly_idx=(40, 80, 120))
        metrics = trained.evaluate(df)

        assert set(metrics) == {"precision", "recall", "f1", "confusion_matrix"}
        for key in ("precision", "recall", "f1"):
            assert 0 <= metrics[key] <= 1
        # One confusion-matrix cell per evaluated window, whatever mix of classes.
        n_windows = 150 - 12 + 1
        assert sum(sum(row) for row in metrics["confusion_matrix"]) == n_windows

    def test_evaluate_detects_planted_anomalies(self, trained):
        """Spikes planted 25 rows apart (so plenty of windows stay clean and
        both classes exist) should mostly be caught without flooding false alerts."""
        df = _synthetic_df(200, seed=5, anomaly_idx=tuple(range(20, 200, 25)))
        metrics = trained.evaluate(df)

        assert metrics["recall"] > 0.5
        assert metrics["precision"] > 0.5

    def test_evaluate_requires_anomaly_column(self, trained):
        with pytest.raises(ValueError, match="'anomaly' column"):
            trained.evaluate(_synthetic_df(50).drop(columns=["anomaly"]))

    # ---- persistence --------------------------------------------------

    def test_save_before_training_raises(self, anomaly_detector, temp_data_dir):
        with pytest.raises(NotTrainedError, match="trained before saving"):
            anomaly_detector.save(temp_data_dir / "nope")

    def test_load_missing_path_raises(self, temp_data_dir):
        with pytest.raises(FileNotFoundError):
            AnomalyDetector.load(temp_data_dir / "does_not_exist")

    def test_save_load_roundtrip(self, trained, temp_data_dir):
        """save() writes a directory; load() is a classmethod returning a
        ready-to-use detector that scores identically."""
        model_dir = temp_data_dir / "anomaly_detector"
        trained.save(model_dir)

        assert (model_dir / "model.keras").exists()
        assert (model_dir / "scaler.joblib").exists()
        config = json.loads((model_dir / "config.json").read_text())
        assert config["threshold"] == trained.threshold
        assert config["seq_len"] == 12
        assert config["feature_columns"] == FEATURE_COLUMNS

        loaded = AnomalyDetector.load(model_dir)
        assert loaded._is_trained is True
        assert loaded.threshold == trained.threshold

        sequences = trained.sequences_from_df(_synthetic_df(80, seed=9))
        original_errors, _ = trained.detect(sequences)
        loaded_errors, _ = loaded.detect(sequences)
        np.testing.assert_allclose(original_errors, loaded_errors, rtol=1e-4, atol=1e-6)

    # ---- thresholding / reproducibility -------------------------------

    def test_threshold_computation(self, anomaly_detector, sample_sensor_data):
        """Test threshold computation during training."""
        # Train with different percentiles
        for percentile in [90, 95, 99]:
            detector = AnomalyDetector(percentile=percentile)
            detector.train(sample_sensor_data, epochs=2, batch_size=16)

            assert detector._threshold > 0

            # Higher percentile should give higher threshold
            if percentile == 99:
                high_threshold = detector._threshold
            elif percentile == 90:
                low_threshold = detector._threshold

        assert high_threshold > low_threshold

    def test_reproducibility(self, anomaly_detector, sample_sensor_data):
        """Test that training is reproducible with same seed."""
        # Set seed for reproducibility
        np.random.seed(42)

        # First training
        anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)
        threshold1 = anomaly_detector._threshold

        # Reset and train again with same seed
        anomaly_detector._model = None
        anomaly_detector._scaler = None
        anomaly_detector._threshold = None
        anomaly_detector._is_trained = False

        np.random.seed(42)
        anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)
        threshold2 = anomaly_detector._threshold

        # Thresholds should be very close (may not be exactly equal due to TF non-determinism)
        assert abs(threshold1 - threshold2) < 0.1
