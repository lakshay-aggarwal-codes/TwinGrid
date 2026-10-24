"""
Pytest configuration and shared fixtures for the digital twin test suite.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.anomaly_detector import AnomalyDetector
from src.digital_twin import CoolingMode, DigitalTwin
from src.lstm_model import DataPipeline


@pytest.fixture(autouse=True)
def _isolated_webhook_delivery_log(tmp_path, monkeypatch):
    """Task 29: a real webhook delivery is logged to a file (src/webhook_deliveries.py). Keep it out of the repo's data/."""
    from src import webhook_deliveries

    monkeypatch.setattr(webhook_deliveries, "LOG_PATH", tmp_path / "webhook_deliveries.json")


@pytest.fixture
def sample_sensor_data():
    """Create sample sensor data for testing."""
    np.random.seed(42)
    n_samples = 1000

    # Generate timestamps
    start_time = datetime(2024, 1, 1)
    timestamps = [start_time + timedelta(minutes=5 * i) for i in range(n_samples)]

    # Generate realistic sensor data
    data = {
        "timestamp": timestamps,
        "server_utilisation": np.clip(
            0.4 + 0.5 * np.sin(np.linspace(0, 4 * np.pi, n_samples)) + np.random.normal(0, 0.1, n_samples), 0, 1
        ),
        "outside_temp_C": 20 + 10 * np.sin(np.linspace(0, 2 * np.pi, n_samples)) + np.random.normal(0, 2, n_samples),
        "server_inlet_temp_C": 18
        + 5 * np.sin(np.linspace(0, 2 * np.pi, n_samples))
        + np.random.normal(0, 1, n_samples),
        "server_outlet_temp_C": 25
        + 8 * np.sin(np.linspace(0, 2 * np.pi, n_samples))
        + np.random.normal(0, 2, n_samples),
        "it_power_kw": 200
        + 200
        * np.clip(0.4 + 0.5 * np.sin(np.linspace(0, 4 * np.pi, n_samples)) + np.random.normal(0, 0.1, n_samples), 0, 1),
        "cooling_power_kw": 50 + 50 * np.sin(np.linspace(0, 2 * np.pi, n_samples)) + np.random.normal(0, 10, n_samples),
        "total_power_kw": 250 + 250 * np.sin(np.linspace(0, 2 * np.pi, n_samples)) + np.random.normal(0, 20, n_samples),
        "pue": 1.2 + 0.3 * np.sin(np.linspace(0, 2 * np.pi, n_samples)) + np.random.normal(0, 0.05, n_samples),
        "water_flow_lpm": 30 + 20 * np.sin(np.linspace(0, 2 * np.pi, n_samples)) + np.random.normal(0, 5, n_samples),
        "water_consumed_L": np.cumsum(np.random.uniform(0, 1, n_samples)),
        "wue": 0.01 + 0.02 * np.sin(np.linspace(0, 2 * np.pi, n_samples)) + np.random.normal(0, 0.005, n_samples),
        "humidity_pct": 40 + 20 * np.sin(np.linspace(0, 2 * np.pi, n_samples)) + np.random.normal(0, 5, n_samples),
        "water_pressure_bar": 2.5
        + 1.0 * np.sin(np.linspace(0, 2 * np.pi, n_samples))
        + np.random.normal(0, 0.2, n_samples),
        "cooling_mode": np.random.choice(["free_air", "closed_loop", "evaporative", "hybrid"], n_samples),
        "anomaly": np.zeros(n_samples),  # Start with no anomalies
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
        max_it_power_kw=500.0, idle_power_fraction=0.4, air_flow_m3_s=8.0, initial_cooling_mode=CoolingMode.CLOSED_LOOP
    )


@pytest.fixture
def data_pipeline():
    """Create a DataPipeline instance for testing."""
    return DataPipeline(seq_len=12, horizon=6, train_ratio=0.8)


@pytest.fixture
def anomaly_detector():
    """Create an AnomalyDetector instance for testing."""
    return AnomalyDetector(seq_len=12, percentile=95)


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


# ----------------------------------------------------------------------------- markers (T11)
# Registered here (pytest.ini uses --strict-markers and is not part of T11) so CI can select by marker.
_CI_MARKERS = {
    "postgres": "needs a real PostgreSQL (TWINGRID_TEST_PG_URL); run by the test-postgres CI job only",
    "slow": "slow test",
    "requires_tf": "needs TensorFlow installed",
    "requires_sb3": "needs stable-baselines3 installed",
}


def pytest_configure(config):
    for name, description in _CI_MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {description}")


_PG_ENV_IN_REASON = re.compile(r"TEST_POSTGRES_URL|TWINGRID_TEST_PG_\w*URL")


def _skips_without_a_postgres_url(item) -> bool:
    """True if the test carries a skipif whose reason names one of the PostgreSQL test URL variables."""
    for marker in item.iter_markers("skipif"):
        if _PG_ENV_IN_REASON.search(str(marker.kwargs.get("reason", ""))):
            return True
    return False


def pytest_collection_modifyitems(config, items):
    """Mark the PostgreSQL-only tests so `-m "not postgres"` really leaves them to the test-postgres job.

    They carry no marker, only a skipif on a URL variable; some are not named "postgres" (test_pg_*, the pg parameter of
    test_telemetry_ingest.py). Unmarked, they skip in the main job and the CI skip gate fails.
    """
    for item in items:
        if item.get_closest_marker("postgres") is not None:
            continue
        if "postgres" in item.name or _skips_without_a_postgres_url(item):
            item.add_marker(pytest.mark.postgres)


def _own_root_handlers() -> list:
    """The root logger's handlers except pytest's own capture handlers (pytest swaps those in and out per phase)."""
    import logging

    return [h for h in logging.root.handlers if not type(h).__module__.startswith("_pytest")]


@pytest.fixture(autouse=True)
def _logging_state_must_not_leak():
    """A test must leave ``logging.disable`` and the root logger's handlers as it found them.

    bench_suite.py once called ``logging.disable(CRITICAL)`` and never undid it, silencing 100+ later tests. The state is
    restored either way (so one leak cannot cascade), and the offending test FAILS so the next leak is named at its source.
    """
    import logging

    disable_before = logging.root.manager.disable
    handlers_before = _own_root_handlers()
    yield
    disable_after = logging.root.manager.disable
    handlers_after = _own_root_handlers()
    logging.disable(disable_before)
    for handler in handlers_after:
        if handler not in handlers_before:
            logging.root.removeHandler(handler)
    for handler in handlers_before:
        if handler not in logging.root.handlers:
            logging.root.addHandler(handler)
    problems = []
    if disable_after != disable_before:
        problems.append(f"logging.disable changed from {disable_before} to {disable_after}")
    if handlers_after != handlers_before:
        problems.append(f"root logger handlers changed: {handlers_before!r} -> {handlers_after!r}")
    assert not problems, "this test leaked logging state (restored here): " + "; ".join(problems)
