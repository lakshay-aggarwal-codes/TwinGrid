"""Tests for src/predictive_maintenance -- the naive baseline (required
before trusting the LSTM), evaluation metrics, and data-driven low-variance
sensor selection."""

import numpy as np
import pandas as pd
import pytest

from src.predictive_maintenance.model import evaluate, naive_baseline_predict


class TestNaiveBaseline:
    def test_predicts_constant_median(self):
        train_rul = np.array([10, 20, 30, 40, 50])
        pred = naive_baseline_predict(train_rul, n_test_units=4)
        assert len(pred) == 4
        assert np.all(pred == 30.0)  # median of [10,20,30,40,50]

    def test_handles_even_length_training_set(self):
        train_rul = np.array([10, 20, 30, 40])
        pred = naive_baseline_predict(train_rul, n_test_units=1)
        assert pred[0] == 25.0  # median of an even-length array


class TestEvaluate:
    def test_perfect_predictions_score_zero_error(self):
        y = np.array([10.0, 20.0, 30.0])
        metrics = evaluate(y, y.copy())
        assert metrics["mae"] == 0.0
        assert metrics["rmse"] == 0.0
        assert metrics["r2"] == pytest.approx(1.0)

    def test_metrics_are_all_present(self):
        y_true = np.array([10.0, 20.0, 30.0])
        y_pred = np.array([12.0, 18.0, 33.0])
        metrics = evaluate(y_true, y_pred)
        assert set(metrics.keys()) == {"mae", "rmse", "r2"}
        assert metrics["mae"] > 0


class TestFeatureSelection:
    def test_drops_low_variance_columns(self):
        """A near-constant column (matching FD001's near-constant
        operating-condition sensors) should be dropped; a genuinely
        varying one should be kept."""
        from src.predictive_maintenance.data_loader import CMAPSSDataset

        df = pd.DataFrame({
            "sensor_1": np.random.normal(50, 10, 100),  # real variance -- keep
            "sensor_2": np.full(100, 5.0),               # constant -- drop
            "op_setting_1": np.full(100, 1.0) + np.random.normal(0, 1e-6, 100),  # near-constant -- drop
        })
        dataset = CMAPSSDataset()
        selected = dataset._select_features(df, std_threshold=1e-3)
        assert "sensor_1" in selected
        assert "sensor_2" not in selected
        assert "op_setting_1" not in selected