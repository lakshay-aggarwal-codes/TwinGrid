"""
Tests for DataPipeline class in lstm_model.py.

Tests data loading, cleaning, sequence creation, and preprocessing functionality.
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from src.lstm_model import DataPipeline, DEFAULT_FEATURE_COLUMNS, TARGET_COLUMN


class TestDataPipeline:
    """Test suite for DataPipeline class."""

    def test_init(self, data_pipeline):
        """Test DataPipeline initialization."""
        assert data_pipeline.seq_len == 12
        assert data_pipeline.horizon == 6
        assert data_pipeline.train_ratio == 0.8
        assert data_pipeline.feature_columns == DEFAULT_FEATURE_COLUMNS
        assert data_pipeline.target_column == TARGET_COLUMN
        assert data_pipeline.scaler is None
        assert data_pipeline.data is None

    def test_init_custom_params(self):
        """Test DataPipeline initialization with custom parameters."""
        custom_features = ["server_utilisation", "outside_temp_C"]
        pipeline = DataPipeline(
            seq_len=10,
            horizon=5,
            train_ratio=0.7,
            feature_columns=custom_features,
            target_column="server_outlet_temp_C"
        )
        assert pipeline.seq_len == 10
        assert pipeline.horizon == 5
        assert pipeline.train_ratio == 0.7
        assert pipeline.feature_columns == custom_features
        assert pipeline.target_column == "server_outlet_temp_C"

    def test_load_data_from_csv(self, data_pipeline, sample_csv_file):
        """Test loading data from CSV file."""
        data_pipeline.load_data(sample_csv_file)
        
        assert data_pipeline.data is not None
        assert isinstance(data_pipeline.data, pd.DataFrame)
        assert len(data_pipeline.data) > 0
        assert all(col in data_pipeline.data.columns for col in data_pipeline.feature_columns)
        assert data_pipeline.target_column in data_pipeline.data.columns

    def test_load_data_from_dataframe(self, data_pipeline, sample_sensor_data):
        """Test loading data from pandas DataFrame."""
        data_pipeline.load_data(sample_sensor_data)
        
        assert data_pipeline.data is not None
        assert len(data_pipeline.data) == len(sample_sensor_data)
        assert data_pipeline.data.equals(sample_sensor_data)

    def test_load_data_missing_file(self, data_pipeline):
        """Test loading data from non-existent file."""
        with pytest.raises(FileNotFoundError):
            data_pipeline.load_data("non_existent_file.csv")

    def test_load_data_missing_columns(self, data_pipeline, temp_data_dir):
        """Test loading data with missing required columns."""
        # Create CSV with missing columns
        incomplete_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="5min"),
            "server_utilisation": np.random.random(100)
            # Missing other required columns
        })
        
        csv_path = temp_data_dir / "incomplete_data.csv"
        incomplete_data.to_csv(csv_path, index=False)
        
        with pytest.raises(KeyError):
            data_pipeline.load_data(csv_path)

    def test_clean_data(self, data_pipeline, sample_sensor_data):
        """Test data cleaning functionality."""
        # Add some null values and outliers
        dirty_data = sample_sensor_data.copy()
        dirty_data.loc[10:15, "server_utilisation"] = np.nan
        dirty_data.loc[20, "server_outlet_temp_C"] = 100  # Outlier
        dirty_data.loc[30, "it_power_kw"] = -10  # Invalid negative value
        
        data_pipeline.load_data(dirty_data)
        original_length = len(data_pipeline.data)
        
        data_pipeline.clean_data()
        
        # Check that null values are filled
        assert not data_pipeline.data["server_utilisation"].isnull().any()
        
        # Check that data length is preserved (nulls filled, not dropped)
        assert len(data_pipeline.data) == original_length

    def test_create_sequences(self, data_pipeline, sample_sensor_data):
        """Test sequence creation for LSTM."""
        data_pipeline.load_data(sample_sensor_data)
        data_pipeline.clean_data()
        
        sequences, targets = data_pipeline.create_sequences()
        
        # Check sequence shapes
        expected_seq_len = len(data_pipeline.data) - data_pipeline.seq_len - data_pipeline.horizon + 1
        assert sequences.shape[0] == expected_seq_len
        assert sequences.shape[1] == data_pipeline.seq_len
        assert sequences.shape[2] == len(data_pipeline.feature_columns)
        
        # Check target shapes
        assert targets.shape[0] == expected_seq_len
        assert len(targets.shape) == 1  # Should be 1D array

    def test_create_sequences_insufficient_data(self, data_pipeline):
        """Test sequence creation with insufficient data."""
        # Create very small dataset
        small_data = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=10, freq="5min"),
            "server_utilisation": np.random.random(10),
            "outside_temp_C": np.random.random(10),
            "server_inlet_temp_C": np.random.random(10),
            "server_outlet_temp_C": np.random.random(10),
            "it_power_kw": np.random.random(10),
            "cooling_power_kw": np.random.random(10),
            "total_power_kw": np.random.random(10),
            "pue": np.random.random(10),
            "water_flow_lpm": np.random.random(10),
            "humidity_pct": np.random.random(10)
        })
        
        data_pipeline.load_data(small_data)
        data_pipeline.clean_data()
        
        sequences, targets = data_pipeline.create_sequences()
        
        # Should have very few or no sequences
        assert sequences.shape[0] >= 0
        assert targets.shape[0] == sequences.shape[0]

    def test_split_data(self, data_pipeline, sample_sensor_data):
        """Test train/test data splitting."""
        data_pipeline.load_data(sample_sensor_data)
        data_pipeline.clean_data()
        sequences, targets = data_pipeline.create_sequences()
        
        X_train, X_test, y_train, y_test = data_pipeline.split_data(sequences, targets)
        
        # Check split ratios
        total_samples = len(sequences)
        expected_train_size = int(total_samples * data_pipeline.train_ratio)
        
        assert len(X_train) == expected_train_size
        assert len(X_test) == total_samples - expected_train_size
        assert len(y_train) == len(X_train)
        assert len(y_test) == len(X_test)

    def test_split_data_custom_ratio(self, data_pipeline, sample_sensor_data):
        """Test train/test data splitting with custom ratio."""
        data_pipeline.train_ratio = 0.6
        data_pipeline.load_data(sample_sensor_data)
        data_pipeline.clean_data()
        sequences, targets = data_pipeline.create_sequences()
        
        X_train, X_test, y_train, y_test = data_pipeline.split_data(sequences, targets)
        
        total_samples = len(sequences)
        expected_train_size = int(total_samples * 0.6)
        
        assert len(X_train) == expected_train_size
        assert len(X_test) == total_samples - expected_train_size

    def test_fit_scaler(self, data_pipeline, sample_sensor_data):
        """Test scaler fitting on training data."""
        data_pipeline.load_data(sample_sensor_data)
        data_pipeline.clean_data()
        sequences, targets = data_pipeline.create_sequences()
        X_train, X_test, y_train, y_test = data_pipeline.split_data(sequences, targets)
        
        # Fit scaler on training data
        data_pipeline.fit_scaler(X_train)
        
        assert data_pipeline.scaler is not None
        
        # Test scaling
        X_train_scaled = data_pipeline.scale_data(X_train)
        X_test_scaled = data_pipeline.scale_data(X_test)
        
        # Check shapes are preserved
        assert X_train_scaled.shape == X_train.shape
        assert X_test_scaled.shape == X_test.shape
        
        # Check that training data is roughly in [0, 1] range
        assert X_train_scaled.min() >= 0
        assert X_train_scaled.max() <= 1.1  # Allow small tolerance

    def test_scale_data_without_scaler(self, data_pipeline):
        """Test scaling data without fitting scaler first."""
        dummy_data = np.random.random((100, 12, 10))
        
        with pytest.raises(ValueError, match="Scaler not fitted"):
            data_pipeline.scale_data(dummy_data)

    def test_prepare_data_complete_pipeline(self, data_pipeline, sample_sensor_data):
        """Test complete data preparation pipeline."""
        X_train, X_test, y_train, y_test = data_pipeline.prepare_data(sample_sensor_data)
        
        # Check that all outputs are numpy arrays
        assert isinstance(X_train, np.ndarray)
        assert isinstance(X_test, np.ndarray)
        assert isinstance(y_train, np.ndarray)
        assert isinstance(y_test, np.ndarray)
        
        # Check shapes
        assert X_train.shape[1] == data_pipeline.seq_len
        assert X_train.shape[2] == len(data_pipeline.feature_columns)
        assert X_test.shape[1] == data_pipeline.seq_len
        assert X_test.shape[2] == len(data_pipeline.feature_columns)
        
        # Check that scaler was fitted
        assert data_pipeline.scaler is not None
        
        # Check train/test split
        total_sequences = X_train.shape[0] + X_test.shape[0]
        train_ratio = X_train.shape[0] / total_sequences
        assert abs(train_ratio - data_pipeline.train_ratio) < 0.01

    def test_prepare_data_with_validation(self, data_pipeline, sample_sensor_data):
        """Test data preparation with validation split."""
        X_train, X_val, X_test, y_train, y_val, y_test = data_pipeline.prepare_data(
            sample_sensor_data, validation_split=0.1
        )
        
        # Check that we have three splits
        assert X_train.shape[0] > 0
        assert X_val.shape[0] > 0
        assert X_test.shape[0] > 0
        
        # Check that validation split is approximately correct
        total_samples = X_train.shape[0] + X_val.shape[0] + X_test.shape[0]
        val_ratio = X_val.shape[0] / total_samples
        assert abs(val_ratio - 0.1) < 0.01

    def test_feature_column_validation(self, data_pipeline, sample_sensor_data):
        """Test validation of feature columns."""
        # Remove a required column
        incomplete_data = sample_sensor_data.drop(columns=["server_utilisation"])
        
        with pytest.raises(KeyError):
            data_pipeline.prepare_data(incomplete_data)

    def test_target_column_validation(self, data_pipeline, sample_sensor_data):
        """Test validation of target column."""
        # Remove target column
        incomplete_data = sample_sensor_data.drop(columns=["server_outlet_temp_C"])
        
        with pytest.raises(KeyError):
            data_pipeline.prepare_data(incomplete_data)

    def test_data_types(self, data_pipeline, sample_sensor_data):
        """Test that data types are handled correctly."""
        data_pipeline.prepare_data(sample_sensor_data)
        
        # Check that the loaded data has correct types
        assert pd.api.types.is_datetime64_any_dtype(data_pipeline.data["timestamp"])
        assert pd.api.types.is_numeric_dtype(data_pipeline.data["server_utilisation"])
        assert pd.api.types.is_numeric_dtype(data_pipeline.data["server_outlet_temp_C"])

    def test_reproducibility(self, data_pipeline, sample_sensor_data):
        """Test that data preparation is reproducible."""
        # First preparation
        X_train1, X_test1, y_train1, y_test1 = data_pipeline.prepare_data(sample_sensor_data)
        
        # Reset and prepare again
        data_pipeline.scaler = None
        data_pipeline.data = None
        X_train2, X_test2, y_train2, y_test2 = data_pipeline.prepare_data(sample_sensor_data)
        
        # Results should be identical
        np.testing.assert_array_equal(X_train1, X_train2)
        np.testing.assert_array_equal(X_test1, X_test2)
        np.testing.assert_array_equal(y_train1, y_train2)
        np.testing.assert_array_equal(y_test1, y_test2)
