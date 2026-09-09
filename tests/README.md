# Digital Twin Test Suite

This directory contains comprehensive tests for the digital twin system.

## Test Structure

### Test Files

- **`test_digital_twin.py`** - Tests for the core DigitalTwin simulation engine
- **`test_data_pipeline.py`** - Tests for the LSTM data preprocessing pipeline
- **`test_anomaly_detector.py`** - Tests for the anomaly detection system
- **`simple_tests.py`** - Basic functionality tests (no complex dependencies)

### Configuration

- **`conftest.py`** - Pytest fixtures and shared test configuration
- **`pytest.ini`** - Pytest configuration file
- **`test_requirements.txt`** - Test-specific dependencies

## Running Tests

### Simple Tests (Recommended)
```bash
python tests/simple_tests.py
```

### Full Pytest Suite (requires compatible dependencies)
```bash
pytest tests/ -v
```

### Specific Test Module
```bash
pytest tests/test_digital_twin.py -v
```

### With Coverage
```bash
pytest tests/ --cov=src --cov-report=html
```

## Test Coverage

### DigitalTwin Tests
- ✅ Initialization with default and custom parameters
- ✅ IT power computation and validation
- ✅ Cooling power computation for all modes
- ✅ Water consumption calculations
- ✅ Simulation step execution
- ✅ Safety constraint checking
- ✅ Energy balance validation
- ✅ Cooling mode physics consistency
- ✅ Multiple step consistency
- ✅ Extreme condition handling

### DataPipeline Tests
- ✅ Initialization and configuration
- ✅ Data loading from CSV and DataFrame
- ✅ Data cleaning and preprocessing
- ✅ Sequence creation for LSTM
- ✅ Train/test data splitting
- ✅ Scaler fitting and transformation
- ✅ Complete pipeline execution
- ✅ Error handling for invalid data

### AnomalyDetector Tests
- ✅ Initialization with custom parameters
- ✅ Model building and architecture
- ✅ Data preparation for training
- ✅ Training on normal and anomalous data
- ✅ Anomaly detection and evaluation
- ✅ Model saving and loading
- ✅ Threshold computation
- ✅ Synthetic anomaly testing
- ✅ Reproducibility validation

## Test Data

### Fixtures
- `sample_sensor_data` - Realistic sensor data with known anomalies
- `digital_twin` - Configured DigitalTwin instance
- `data_pipeline` - DataPipeline instance for testing
- `anomaly_detector` - AnomalyDetector instance for testing
- `temp_data_dir` - Temporary directory for file operations

### Data Characteristics
- 1000 samples of sensor data
- Realistic temperature, power, and water metrics
- Injected anomalies for testing detection
- Proper timestamps and data types

## Logging Integration

All tests integrate with the comprehensive logging system:
- Function entry/exit logging
- Error logging with stack traces
- Training progress logging
- Simulation step results logging

Test execution logs are written to `logs/digital_twin.log`.

## Troubleshooting

### Pytest Compatibility Issues
If you encounter pytest compatibility issues, use the simple tests:
```bash
python tests/simple_tests.py
```

### Missing Dependencies
Install test dependencies:
```bash
pip install -r tests/test_requirements.txt
```

### TensorFlow Issues
Some ML tests require TensorFlow. Install with:
```bash
pip install tensorflow
```

## Best Practices

1. **Run tests before commits** - Ensure all functionality works
2. **Check logs** - Review `logs/digital_twin.log` for detailed execution info
3. **Use fixtures** - Leverage shared test data for consistency
4. **Test edge cases** - Verify behavior under extreme conditions
5. **Validate physics** - Ensure simulation maintains physical constraints

## Adding New Tests

1. Create test methods following the `test_*` naming convention
2. Use descriptive test names that explain what is being tested
3. Include assertions for both success and failure cases
4. Add logging to verify integration
5. Update this README when adding new test categories

## Continuous Integration

These tests are designed to run in CI/CD pipelines:
- Fast execution for quick feedback
- Comprehensive coverage for reliability
- Clear output for debugging failures
- Isolated test execution for parallel runs
