"""
Training script: generate data, train LSTM, anomaly detector, RL optimizer.

Steps:
  1. Generate 90 days sensor data (data_generator.generate_sensor_data)
  2. Train LSTM ThermalForecaster via DataPipeline
  3. Train AnomalyDetector on normal data
  4. Train JointOptimizer (PPO) for water+energy optimization
  5. Baseline PUE from rule-based DigitalTwin
  6. Compare normal vs drought scenarios

Runs all training pipelines and saves models to models/ directory.
Target runtime: < 30 minutes on CPU.
Paths are relative to project root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _root(path: str) -> Path:
    """Resolve path relative to project root."""
    return PROJECT_ROOT / path


class _NoOpPBar:
    """Fallback when tqdm not installed."""
    def update(self, n=1): pass
    def set_postfix_str(self, s): pass
    def close(self): pass


def main() -> None:
    import pandas as pd
    try:
        from tqdm import tqdm
        pbar_fn = lambda: tqdm(total=6, desc="Training pipeline", unit="step")
    except ImportError:
        pbar_fn = lambda: _NoOpPBar()

    from src.anomaly_detector import AnomalyDetector
    from src.data_generator import generate_sensor_data
    from src.digital_twin import DigitalTwin
    from src.lstm_model import DataPipeline, ThermalForecaster
    from src.optimizer import JointOptimizer

    metrics: dict[str, float] = {}
    pbar = pbar_fn()

    # -------------------------------------------------------------------------
    # 1. Generate data
    # -------------------------------------------------------------------------
    pbar.set_postfix_str("Generating data")
    print("\n" + "=" * 60)
    print("1. GENERATING SENSOR DATA (90 days)")
    print("=" * 60)
    data_path = _root("data/raw/sensor_data.csv")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    df = generate_sensor_data(days=90, seed=42)
    df.to_csv(data_path, index=False)
    print(f"   Saved to {data_path} ({len(df):,} rows)")
    pbar.update(1)

    # -------------------------------------------------------------------------
    # 2. Train LSTM Forecaster
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("2. TRAINING LSTM THERMAL FORECASTER")
    print("=" * 60)
    pbar.set_postfix_str("LSTM forecaster")
    pipe = DataPipeline(seq_len=12, horizon=6, train_ratio=0.8)
    pipe.load_csv(data_path)
    X_train, y_train, X_test, y_test = pipe.prepare()

    forecaster = ThermalForecaster()
    forecaster.train(
        X_train, y_train,
        epochs=30,
        patience=8,
        checkpoint_dir=_root("models/forecaster"),
    )
    preds, rmse, mae = forecaster.evaluate(X_test, y_test)
    metrics["lstm_rmse"] = rmse
    metrics["lstm_mae"] = mae

    _root("models/forecaster").mkdir(parents=True, exist_ok=True)
    forecaster.save(_root("models/forecaster/thermal.keras"))
    pipe.save_scaler(_root("models/forecaster/scaler.joblib"))
    print(f"   RMSE: {rmse:.4f}, MAE: {mae:.4f}")
    print(f"   Saved to models/forecaster/")
    pbar.update(1)

    # -------------------------------------------------------------------------
    # 3. Train Anomaly Detector
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("3. TRAINING ANOMALY DETECTOR")
    print("=" * 60)
    pbar.set_postfix_str("Anomaly detector")
    df_anomaly = pd.read_csv(data_path)
    df_anomaly["timestamp"] = pd.to_datetime(df_anomaly["timestamp"])
    df_anomaly = df_anomaly.sort_values("timestamp").reset_index(drop=True)

    detector = AnomalyDetector(verbose=0)
    detector.train(df_anomaly, epochs=20, patience=5)
    eval_metrics = detector.evaluate(df_anomaly)
    metrics["anomaly_f1"] = eval_metrics["f1"]
    metrics["anomaly_precision"] = eval_metrics["precision"]
    metrics["anomaly_recall"] = eval_metrics["recall"]

    _root("models/anomaly").mkdir(parents=True, exist_ok=True)
    detector.save(_root("models/anomaly"))
    print(f"   F1: {eval_metrics['f1']:.4f}, P: {eval_metrics['precision']:.4f}, R: {eval_metrics['recall']:.4f}")
    print(f"   Saved to models/anomaly/")
    pbar.update(1)

    # -------------------------------------------------------------------------
    # 4. Train RL Optimizer
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("4. TRAINING RL OPTIMIZER (PPO)")
    print("=" * 60)
    pbar.set_postfix_str("RL optimizer")
    optimizer = JointOptimizer(alpha=0.5, beta=0.3, gamma=0.2)
    optimizer.train(
        total_timesteps=50_000,
        n_envs=4,
        water_stress=0.0,
    )
    _root("models/optimizer").mkdir(parents=True, exist_ok=True)
    optimizer.save(_root("models/optimizer"))
    print(f"   Saved to models/optimizer/")
    pbar.update(1)

    # -------------------------------------------------------------------------
    # 5. Baseline PUE (rule-based DigitalTwin)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("5. BASELINE PUE (rule-based)")
    print("=" * 60)
    pbar.set_postfix_str("Baseline PUE")
    twin = DigitalTwin()
    n_steps = 288  # 24 hours
    util_profile = [0.5 + 0.3 * (i % 12) / 12 for i in range(n_steps)]
    temp_profile = [22 + 3 * (i % 24) / 24 for i in range(n_steps)]
    df_baseline = twin.run_scenario(
        n_steps=n_steps,
        util_profile=util_profile,
        temp_profile=temp_profile,
        use_auto_cooling=True,
        water_stress=0.0,
    )
    pue_baseline = df_baseline["pue"].mean()
    metrics["pue_baseline"] = pue_baseline
    print(f"   Baseline avg PUE: {pue_baseline:.4f}")
    pbar.update(1)

    # -------------------------------------------------------------------------
    # 6. Compare scenarios (normal vs drought)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("6. COMPARING NORMAL vs DROUGHT SCENARIOS")
    print("=" * 60)
    pbar.set_postfix_str("Scenario comparison")
    comparison = optimizer.compare_scenarios(normal_stress=0.0, drought_stress=0.8)
    pue_optimized_normal = comparison["normal"]["mean_pue"]
    pue_optimized_drought = comparison["drought"]["mean_pue"]
    metrics["pue_optimized_normal"] = pue_optimized_normal
    metrics["pue_optimized_drought"] = pue_optimized_drought
    print(f"   Normal stress  PUE: {pue_optimized_normal:.4f}")
    print(f"   Drought stress PUE: {pue_optimized_drought:.4f}")
    print(f"   Water reduction (drought): {comparison['comparison']['water_reduction_pct']:.1f}%")
    pbar.update(1)
    pbar.close()

    # -------------------------------------------------------------------------
    # 7. Final metrics table
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("FINAL METRICS")
    print("=" * 60)
    print(f"""
    | Metric                    | Value    |
    |---------------------------|----------|
    | LSTM RMSE (°C)            | {metrics.get('lstm_rmse', 0):.4f}   |
    | LSTM MAE (°C)             | {metrics.get('lstm_mae', 0):.4f}   |
    | Anomaly F1                | {metrics.get('anomaly_f1', 0):.4f}   |
    | Anomaly Precision         | {metrics.get('anomaly_precision', 0):.4f}   |
    | Anomaly Recall            | {metrics.get('anomaly_recall', 0):.4f}   |
    | PUE (baseline, rule-based)| {metrics.get('pue_baseline', 0):.4f}   |
    | PUE (optimized, normal)   | {metrics.get('pue_optimized_normal', 0):.4f}   |
    | PUE (optimized, drought)  | {metrics.get('pue_optimized_drought', 0):.4f}   |
    """)
    pue_improvement = (pue_baseline - pue_optimized_normal) / pue_baseline * 100 if pue_baseline > 0 else 0
    print(f"   PUE improvement (baseline → optimized): {pue_improvement:.1f}%")
    print("\n   All models saved to models/")


if __name__ == "__main__":
    main()
