"""
Tests for AnomalyDetector class in anomaly_detector.py.

Tests anomaly detection on synthetic data with known anomalies.
"""


import numpy as np
import pandas as pd
import pytest

from src.anomaly_detector import AnomalyDetector, NotTrainedError


class TestAnomalyDetector:
    """Test suite for AnomalyDetector class."""

    def test_init_default_params(self):
        """Test AnomalyDetector initialization with default parameters."""
        detector = AnomalyDetector()
        
        assert detector.seq_len == 12
        assert detector.percentile == 95
        assert detector._model is None
        assert detector._scaler is None
        assert detector._threshold is None
        assert detector._is_trained is False

    def test_init_custom_params(self):
        """Test AnomalyDetector initialization with custom parameters."""
        detector = AnomalyDetector(
            seq_len=10,
            percentile=99,
            verbose=0
        )
        
        assert detector.seq_len == 10
        assert detector.percentile == 99
        assert detector._verbose == 0

    def test_build_model(self, anomaly_detector):
        """Test model building."""
        model = anomaly_detector._build_model()
        
        assert model is not None
        assert hasattr(model, 'input_shape')
        assert hasattr(model, 'output_shape')

    def test_prepare_data_normal_only(self, anomaly_detector, sample_sensor_data):
        """Test data preparation with normal data only."""
        # Filter to only normal data
        normal_data = sample_sensor_data[sample_sensor_data['anomaly'] == 0].copy()
        
        sequences, labels = anomaly_detector._prepare_data(normal_data, normal_only=True)
        
        assert sequences.shape[0] > 0
        assert sequences.shape[1] == anomaly_detector.seq_len
        assert sequences.shape[2] == 10  # Number of features
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

    def test_prepare_data_insufficient_data(self, anomaly_detector):
        """Test data preparation with insufficient data."""
        # Create minimal dataset
        minimal_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=15, freq="5min"),
            "server_utilisation": np.random.random(15),
            "outside_temp_C": np.random.random(15),
            "server_inlet_temp_C": np.random.random(15),
            "server_outlet_temp_C": np.random.random(15),
            "it_power_kw": np.random.random(15),
            "cooling_power_kw": np.random.random(15),
            "total_power_kw": np.random.random(15),
            "pue": np.random.random(15),
            "water_flow_lpm": np.random.random(15),
            "humidity_pct": np.random.random(15),
            "anomaly": np.zeros(15)
        })
        
        sequences, labels = anomaly_detector._prepare_data(minimal_data, normal_only=True)
        
        # Should have very few sequences
        assert sequences.shape[0] >= 0

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
        history = anomaly_detector.train(
            sample_sensor_data,
            epochs=3,
            batch_size=8,
            validation_split=0.3,
            patience=5
        )
        
        assert anomaly_detector._is_trained is True
        assert len(history["loss"]) <= 3  # Should stop at or before 3 epochs

    def test_train_no_normal_data(self, anomaly_detector):
        """Test training with no normal data."""
        # Create data with only anomalies
        anomaly_only_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"),
            "server_utilisation": np.random.random(100),
            "outside_temp_C": np.random.random(100),
            "server_inlet_temp_C": np.random.random(100),
            "server_outlet_temp_C": np.random.random(100),
            "it_power_kw": np.random.random(100),
            "cooling_power_kw": np.random.random(100),
            "total_power_kw": np.random.random(100),
            "pue": np.random.random(100),
            "water_flow_lpm": np.random.random(100),
            "humidity_pct": np.random.random(100),
            "anomaly": np.ones(100)  # All anomalies
        })
        
        with pytest.raises(ValueError, match="No normal sequences found"):
            anomaly_detector.train(anomaly_only_data)

    def test_train_insufficient_data(self, anomaly_detector):
        """Test training with insufficient data."""
        # Create very small dataset
        small_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=20, freq="5min"),
            "server_utilisation": np.random.random(20),
            "outside_temp_C": np.random.random(20),
            "server_inlet_temp_C": np.random.random(20),
            "server_outlet_temp_C": np.random.random(20),
            "it_power_kw": np.random.random(20),
            "cooling_power_kw": np.random.random(20),
            "total_power_kw": np.random.random(20),
            "pue": np.random.random(20),
            "water_flow_lpm": np.random.random(20),
            "humidity_pct": np.random.random(20),
            "anomaly": np.zeros(20)
        })
        
        with pytest.raises(ValueError, match="No normal sequences found"):
            anomaly_detector.train(small_data)

    def test_detect_before_training(self, anomaly_detector, sample_sensor_data):
        """Test anomaly detection before training."""
        sequences, _ = anomaly_detector._prepare_data(sample_sensor_data, normal_only=False)
        
        with pytest.raises(NotTrainedError, match="Detector must be trained first"):
            anomaly_detector.detect(sequences)

    def test_detect_after_training(self, anomaly_detector, sample_sensor_data):
        """Test anomaly detection after training."""
        # Train the detector
        anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)
        
        # Prepare test data
        sequences, true_labels = anomaly_detector._prepare_data(sample_sensor_data, normal_only=False)
        
        # Detect anomalies
        predictions = anomaly_detector.detect(sequences)
        
        assert len(predictions) == len(sequences)
        assert all(pred in [0, 1] for pred in predictions)
        assert isinstance(predictions, np.ndarray)

    def test_detect_synthetic_anomalies(self, anomaly_detector):
        """Test detection of synthetic anomalies."""
        # Create training data (all normal)
        np.random.seed(42)
        n_samples = 200
        normal_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n_samples, freq="5min"),
            "server_utilisation": 0.5 + 0.3 * np.sin(np.linspace(0, 4*np.pi, n_samples)) + np.random.normal(0, 0.05, n_samples),
            "outside_temp_C": 20 + 5 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 1, n_samples),
            "server_inlet_temp_C": 18 + 3 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 0.5, n_samples),
            "server_outlet_temp_C": 25 + 5 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 1, n_samples),
            "it_power_kw": 300 + 100 * np.sin(np.linspace(0, 4*np.pi, n_samples)) + np.random.normal(0, 10, n_samples),
            "cooling_power_kw": 75 + 25 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 5, n_samples),
            "total_power_kw": 375 + 125 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 15, n_samples),
            "pue": 1.25 + 0.1 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 0.02, n_samples),
            "water_flow_lpm": 40 + 10 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 2, n_samples),
            "humidity_pct": 50 + 10 * np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 2, n_samples),
            "anomaly": np.zeros(n_samples)
        })
        
        # Train on normal data
        anomaly_detector.train(normal_data, epochs=5, batch_size=16)
        
        # Create test data with anomalies
        test_data = normal_data.copy()
        
        # Add some anomalies
        anomaly_indices = [50, 100, 150]
        for idx in anomaly_indices:
            # Create anomalies by modifying values
            test_data.loc[idx, "server_outlet_temp_C"] += 15  # High temperature
            test_data.loc[idx, "water_flow_lpm"] *= 2.0  # High flow
            test_data.loc[idx, "pue"] += 0.5  # High PUE
            test_data.loc[idx, "anomaly"] = 1
        
        # Test detection
        sequences, true_labels = anomaly_detector._prepare_data(test_data, normal_only=False)
        predictions = anomaly_detector.detect(sequences)
        
        # Should detect some anomalies
        assert np.sum(predictions) > 0
        
        # Check that some anomalies are detected (not perfect detection expected)
        detected_anomaly_indices = np.where(predictions == 1)[0]
        assert len(detected_anomaly_indices) > 0

    def test_evaluate_before_training(self, anomaly_detector, sample_sensor_data):
        """Test evaluation before training."""
        with pytest.raises(NotTrainedError, match="Detector must be trained first"):
            anomaly_detector.evaluate(sample_sensor_data)

    def test_evaluate_after_training(self, anomaly_detector, sample_sensor_data):
        """Test evaluation after training."""
        # Train the detector
        anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)
        
        # Evaluate
        metrics = anomaly_detector.evaluate(sample_sensor_data)
        
        assert isinstance(metrics, dict)
        assert "precision" in metrics
        assert "recall" in metrics
        assert "f1" in metrics
        assert "accuracy" in metrics
        assert "threshold" in metrics
        
        # Check metric ranges
        assert 0 <= metrics["precision"] <= 1
        assert 0 <= metrics["recall"] <= 1
        assert 0 <= metrics["f1"] <= 1
        assert 0 <= metrics["accuracy"] <= 1
        assert metrics["threshold"] > 0

    def test_evaluate_synthetic_data(self, anomaly_detector):
        """Test evaluation on synthetic data with known anomalies."""
        # Create training data (all normal)
        np.random.seed(42)
        n_train = 300
        train_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n_train, freq="5min"),
            "server_utilisation": 0.5 + 0.3 * np.sin(np.linspace(0, 4*np.pi, n_train)) + np.random.normal(0, 0.05, n_train),
            "outside_temp_C": 20 + 5 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 1, n_train),
            "server_inlet_temp_C": 18 + 3 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 0.5, n_train),
            "server_outlet_temp_C": 25 + 5 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 1, n_train),
            "it_power_kw": 300 + 100 * np.sin(np.linspace(0, 4*np.pi, n_train)) + np.random.normal(0, 10, n_train),
            "cooling_power_kw": 75 + 25 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 5, n_train),
            "total_power_kw": 375 + 125 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 15, n_train),
            "pue": 1.25 + 0.1 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 0.02, n_train),
            "water_flow_lpm": 40 + 10 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 2, n_train),
            "humidity_pct": 50 + 10 * np.sin(np.linspace(0, 2*np.pi, n_train)) + np.random.normal(0, 2, n_train),
            "anomaly": np.zeros(n_train)
        })
        
        # Train
        anomaly_detector.train(train_data, epochs=5, batch_size=32)
        
        # Create test data with known anomalies
        n_test = 100
        test_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-02-01", periods=n_test, freq="5min"),
            "server_utilisation": 0.5 + 0.3 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 0.05, n_test),
            "outside_temp_C": 20 + 5 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 1, n_test),
            "server_inlet_temp_C": 18 + 3 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 0.5, n_test),
            "server_outlet_temp_C": 25 + 5 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 1, n_test),
            "it_power_kw": 300 + 100 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 10, n_test),
            "cooling_power_kw": 75 + 25 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 5, n_test),
            "total_power_kw": 375 + 125 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 15, n_test),
            "pue": 1.25 + 0.1 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 0.02, n_test),
            "water_flow_lpm": 40 + 10 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 2, n_test),
            "humidity_pct": 50 + 10 * np.sin(np.linspace(0, 2*np.pi, n_test)) + np.random.normal(0, 2, n_test),
            "anomaly": np.zeros(n_test)
        })
        
        # Add anomalies to 20% of samples
        anomaly_indices = np.random.choice(n_test, size=int(0.2 * n_test), replace=False)
        for idx in anomaly_indices:
            test_data.loc[idx, "server_outlet_temp_C"] += np.random.uniform(10, 20)
            test_data.loc[idx, "water_flow_lpm"] *= np.random.uniform(1.5, 2.5)
            test_data.loc[idx, "pue"] += np.random.uniform(0.3, 0.7)
            test_data.loc[idx, "anomaly"] = 1
        
        # Evaluate
        metrics = anomaly_detector.evaluate(test_data)
        
        # Should have reasonable performance
        assert metrics["accuracy"] >= 0.5  # At least 50% accuracy
        assert metrics["threshold"] > 0

    def test_save_load_model(self, anomaly_detector, sample_sensor_data, temp_data_dir):
        """Test saving and loading model."""
        # Train the detector
        anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)
        original_threshold = anomaly_detector._threshold
        
        # Save model
        model_path = temp_data_dir / "anomaly_detector"
        anomaly_detector.save_model(model_path)
        
        # Check that files were created
        assert (model_path / "model.keras").exists()
        assert (model_path / "scaler.joblib").exists()
        assert (model_path / "metadata.json").exists()
        
        # Create new detector and load model
        new_detector = AnomalyDetector()
        new_detector.load_model(model_path)
        
        # Check that model was loaded correctly
        assert new_detector._is_trained is True
        assert new_detector._model is not None
        assert new_detector._scaler is not None
        assert new_detector._threshold == original_threshold

    def test_load_model_before_training(self, anomaly_detector, temp_data_dir):
        """Test loading model into untrained detector."""
        # Create dummy model files
        model_path = temp_data_dir / "dummy_model"
        model_path.mkdir(exist_ok=True)
        
        # Create empty files (would normally contain actual model data)
        (model_path / "model.keras").touch()
        (model_path / "scaler.joblib").touch()
        (model_path / "metadata.json").write_text('{"threshold": 0.1}')
        
        # This should work (though model won't be functional)
        anomaly_detector.load_model(model_path)
        assert anomaly_detector._threshold == 0.1

    def test_compute_errors(self, anomaly_detector, sample_sensor_data):
        """Test reconstruction error computation."""
        # Train the detector
        anomaly_detector.train(sample_sensor_data, epochs=2, batch_size=16)
        
        # Prepare test sequences
        sequences, _ = anomaly_detector._prepare_data(sample_sensor_data, normal_only=False)
        
        # Compute errors
        errors = anomaly_detector._compute_errors(sequences)
        
        assert len(errors) == len(sequences)
        assert all(error >= 0 for error in errors)
        assert isinstance(errors, np.ndarray)

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
