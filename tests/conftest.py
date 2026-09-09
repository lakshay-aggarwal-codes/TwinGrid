"""
Pytest configuration and shared fixtures for the digital twin test suite.
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from src.digital_twin import DigitalTwin, CoolingMode, DataCentreState
from src.lstm_model import DataPipeline
from src.anomaly_detector import AnomalyDetector


@pytest.fixture
def sample_sensor_data():
    """Create sample sensor data for testing."""
    np.random.seed(42)
    n_samples = 1000
    
    # Generate timestamps
    start_time = datetime(2024, 1, 1)
    timestamps = [start_time + timedelta(minutes=5*i) for i in range(n_samples)]
    
    # Generate realistic sensor data
    data = {
        "timestamp": timestamps,
        "server_utilisation": np.clip(0.4 + 0.5*np.sin(np.linspace(0, 4*np.pi, n_samples)) + np.random.normal(0, 0.1, n_samples), 0, 1),
        "outside_temp_C": 20 + 10*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 2, n_samples),
        "server_inlet_temp_C": 18 + 5*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 1, n_samples),
        "server_outlet_temp_C": 25 + 8*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 2, n_samples),
        "it_power_kw": 200 + 200*np.clip(0.4 + 0.5*np.sin(np.linspace(0, 4*np.pi, n_samples)) + np.random.normal(0, 0.1, n_samples), 0, 1),
        "cooling_power_kw": 50 + 50*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 10, n_samples),
        "total_power_kw": 250 + 250*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 20, n_samples),
        "pue": 1.2 + 0.3*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 0.05, n_samples),
        "water_flow_lpm": 30 + 20*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 5, n_samples),
        "water_consumed_L": np.cumsum(np.random.uniform(0, 1, n_samples)),
        "wue": 0.01 + 0.02*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 0.005, n_samples),
        "humidity_pct": 40 + 20*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 5, n_samples),
        "water_pressure_bar": 2.5 + 1.0*np.sin(np.linspace(0, 2*np.pi, n_samples)) + np.random.normal(0, 0.2, n_samples),
        "cooling_mode": np.random.choice(["free_air", "closed_loop", "evaporative", "hybrid"], n_samples),
        "anomaly": np.zeros(n_samples)  # Start with no anomalies
    }
    
    # Add some anomalies
    anomaly_indices = np.random.choice(n_samples, size=20, replace=False)
    data["anomaly"][anomaly_indices] = 1
    
    # Make some values anomalous
    for idx in anomaly_indices:
        data["server_outlet_temp_C"][idx] += np.random.uniform(10, 20)  # High temperature
        data["water_pressure_bar"][idx] *= np.random.uniform(0.5, 0.8)  # Low pressure
        data["water_flow_lpm"][idx] *= np.random.uniform(1.5, 2.0)  # High flow
    
    return pd.DataFrame(data)


@pytest.fixture
def digital_twin():
    """Create a DigitalTwin instance for testing."""
    return DigitalTwin(
        max_it_power_kw=500.0,
        idle_power_fraction=0.4,
        air_flow_m3_s=8.0,
        initial_cooling_mode=CoolingMode.CLOSED_LOOP
    )


@pytest.fixture
def data_pipeline():
    """Create a DataPipeline instance for testing."""
    return DataPipeline(
        seq_len=12,
        horizon=6,
        train_ratio=0.8
    )


@pytest.fixture
def anomaly_detector():
    """Create an AnomalyDetector instance for testing."""
    return AnomalyDetector(
        seq_len=12,
        percentile=95
    )


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for testing."""
    temp_dir = Path("tests/temp_data")
    temp_dir.mkdir(exist_ok=True)
    yield temp_dir
    # Cleanup
    if temp_dir.exists():
        import shutil
        shutil.rmtree(temp_dir)


@pytest.fixture
def sample_csv_file(sample_sensor_data, temp_data_dir):
    """Create a sample CSV file for testing."""
    csv_path = temp_data_dir / "sensor_data.csv"
    sample_sensor_data.to_csv(csv_path, index=False)
    return csv_path
