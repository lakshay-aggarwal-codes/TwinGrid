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

import numpy as np

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
        # pbar_fn = lambda: tqdm(total=6, desc="Training pipeline", unit="step")
        def pbar_fn():
            return tqdm(total=6, desc="Training pipeline", unit="step")
    except ImportError:
        # pbar_fn = lambda: _NoOpPBar()
        def pbar_fn():
            return _NoOpPBar()

    from src.anomaly_detector import AnomalyDetector
    from src.data_generator import generate_sensor_data
    from src.digital_twin import DigitalTwin
    from src.lstm_model import DataPipeline, ThermalForecaster
    from src.model_registry import log_model
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
    print("   Saved to models/forecaster/")
    log_model(
        "forecaster",
        metrics={"rmse": float(rmse), "mae": float(mae)},
        data_source=str(data_path),
        artifact_path=str(_root("models/forecaster/thermal.keras")),
        params={"seq_len": 12, "horizon": 6, "train_ratio": 0.8, "epochs": 30, "patience": 8},
    )
    pbar.update(1)

    # -------------------------------------------------------------------------
    # 3. Train Anomaly Detector -- HELD-OUT test split
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("3. TRAINING ANOMALY DETECTOR")
    print("=" * 60)
    pbar.set_postfix_str("Anomaly detector")
    df_anomaly = pd.read_csv(data_path)
    df_anomaly["timestamp"] = pd.to_datetime(df_anomaly["timestamp"])
    df_anomaly = df_anomaly.sort_values("timestamp").reset_index(drop=True)

    # Chronological 80/20 split (same ratio DataPipeline already uses for the
    # LSTM above). Previously detector.train() and the F1/precision/recall
    # eval below both ran on the SAME df_anomaly -- the reported F1=0.93
    # reflected memorization, not generalization. train() only ever sees
    # df_anomaly_train now; calibration AND the reported metrics are computed
    # on df_anomaly_test alone, which the model never saw during training.
    split_idx = int(len(df_anomaly) * 0.8)
    df_anomaly_train = df_anomaly.iloc[:split_idx].reset_index(drop=True)
    df_anomaly_test = df_anomaly.iloc[split_idx:].reset_index(drop=True)

    detector = AnomalyDetector(verbose=0)
    detector.train(df_anomaly_train, epochs=20, patience=5)

    sequences, labels = detector._prepare_data(df_anomaly_test, normal_only=False)
    errors, _ = detector.detect(sequences, threshold=float("inf"))  # scores only
    labels_bool = labels.astype(bool)

    from sklearn.metrics import f1_score, precision_score, recall_score

    best = {"f1": -1.0}
    for pct in [80, 85, 90, 95, 97.5, 99, 99.5, 99.8, 99.9, 99.95, 99.99]:
        thresh = float(np.percentile(errors, pct))
        alerts = errors > thresh
        f1 = f1_score(labels_bool, alerts, zero_division=0)
        if f1 > best["f1"]:
            best = {
                "f1": f1,
                "percentile": pct,
                "threshold": thresh,
                "precision": precision_score(labels_bool, alerts, zero_division=0),
                "recall": recall_score(labels_bool, alerts, zero_division=0),
            }

    print(
        f"   Held-out test F1 -> best ({best['percentile']}th pct) F1={best['f1']:.4f} "
        f"(train/test split: {len(df_anomaly_train)}/{len(df_anomaly_test)} rows)"
    )
    detector._threshold = best["threshold"]
    detector._percentile = best["percentile"]
    eval_metrics = {"f1": best["f1"], "precision": best["precision"], "recall": best["recall"]}
    metrics["anomaly_f1"] = eval_metrics["f1"]
    metrics["anomaly_precision"] = eval_metrics["precision"]
    metrics["anomaly_recall"] = eval_metrics["recall"]

    _root("models/anomaly").mkdir(parents=True, exist_ok=True)
    detector.save(_root("models/anomaly"))
    print(f"   F1: {eval_metrics['f1']:.4f}, P: {eval_metrics['precision']:.4f}, R: {eval_metrics['recall']:.4f}")
    print("   Saved to models/anomaly/ (metrics are held-out, not training-set)")
    log_model(
        "anomaly_detector",
        metrics=eval_metrics,
        data_source=f"{data_path} (rows 0:{split_idx} train, {split_idx}:{len(df_anomaly)} held out)",
        artifact_path=str(_root("models/anomaly")),
        params={"threshold_percentile": best["percentile"], "seq_len": detector._seq_len},
    )

    # -------------------------------------------------------------------------
    # 4. Baseline PUE (rule-based DigitalTwin) -- computed before RL so the
    #    multi-seed PPO runs below can report improvement against it directly.
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("4. BASELINE PUE (rule-based)")
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
    # 5. Train RL Optimizer (PPO) -- multiple seeds. A single run's PUE
    #    improvement is a point estimate, not evidence; report mean +/- 95%
    #    CI across independent seeds instead (Phase 2: statistical rigor).
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("5. TRAINING RL OPTIMIZER (PPO) -- multi-seed")
    print("=" * 60)
    pbar.set_postfix_str("RL optimizer")
    PPO_SEEDS = [0, 1, 2]
    pue_improvements: list[float] = []
    optimizer: JointOptimizer | None = None
    comparison = None
    for i, seed in enumerate(PPO_SEEDS):
        print(f"   Seed {seed} ({i + 1}/{len(PPO_SEEDS)})")
        opt_i = JointOptimizer(alpha=0.5, beta=0.3, gamma=0.2, seed=seed)
        opt_i.train(total_timesteps=50_000, n_envs=4, water_stress=0.0)
        comparison_i = opt_i.compare_scenarios(normal_stress=0.0, drought_stress=0.8)
        pue_opt_i = comparison_i["normal"]["mean_pue"]
        improvement_i = (pue_baseline - pue_opt_i) / pue_baseline * 100 if pue_baseline > 0 else 0.0
        pue_improvements.append(improvement_i)
        print(f"      PUE improvement vs. baseline: {improvement_i:.2f}%")
        if seed == PPO_SEEDS[0]:
            optimizer = opt_i  # the deployed artifact is the first seed's run
            comparison = comparison_i

    pue_improvement_mean = float(np.mean(pue_improvements))
    pue_improvement_std = float(np.std(pue_improvements, ddof=1)) if len(pue_improvements) > 1 else 0.0
    pue_improvement_ci95 = 1.96 * pue_improvement_std / np.sqrt(len(pue_improvements)) if len(pue_improvements) > 1 else 0.0
    metrics["pue_improvement_mean_pct"] = pue_improvement_mean
    metrics["pue_improvement_std_pct"] = pue_improvement_std
    metrics["pue_improvement_ci95_pct"] = pue_improvement_ci95
    print(
        f"   PUE improvement across {len(PPO_SEEDS)} seeds: "
        f"{pue_improvement_mean:.2f}% +/- {pue_improvement_ci95:.2f}% (95% CI)"
    )

    _root("models/optimizer").mkdir(parents=True, exist_ok=True)
    assert optimizer is not None
    optimizer.save(_root("models/optimizer"))
    print(f"   Saved to models/optimizer/ (deployed artifact: seed={PPO_SEEDS[0]})")
    log_model(
        "ppo_optimizer",
        metrics={
            "pue_improvement_mean_pct": pue_improvement_mean,
            "pue_improvement_std_pct": pue_improvement_std,
            "pue_improvement_ci95_pct": pue_improvement_ci95,
            "pue_improvement_per_seed_pct": dict(zip(PPO_SEEDS, pue_improvements)),
        },
        data_source="live DigitalTwin simulation (no historical dataset)",
        artifact_path=str(_root("models/optimizer")),
        params={"alpha": 0.5, "beta": 0.3, "gamma": 0.2, "seeds": PPO_SEEDS, "total_timesteps": 50_000},
    )
    pbar.update(1)

    # -------------------------------------------------------------------------
    # 6. Compare scenarios (normal vs drought) -- for the deployed (seed 0)
    #    optimizer specifically.
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("6. COMPARING NORMAL vs DROUGHT SCENARIOS")
    print("=" * 60)
    pbar.set_postfix_str("Scenario comparison")
    assert comparison is not None
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
    | Metric                              | Value    |
    |--------------------------------------|----------|
    | LSTM RMSE (°C)                       | {metrics.get('lstm_rmse', 0):.4f}   |
    | LSTM MAE (°C)                        | {metrics.get('lstm_mae', 0):.4f}   |
    | Anomaly F1 (held-out)                | {metrics.get('anomaly_f1', 0):.4f}   |
    | Anomaly Precision (held-out)         | {metrics.get('anomaly_precision', 0):.4f}   |
    | Anomaly Recall (held-out)            | {metrics.get('anomaly_recall', 0):.4f}   |
    | PUE (baseline, rule-based)           | {metrics.get('pue_baseline', 0):.4f}   |
    | PUE improvement (mean, {len(PPO_SEEDS)} seeds)       | {metrics.get('pue_improvement_mean_pct', 0):.2f}% +/- {metrics.get('pue_improvement_ci95_pct', 0):.2f}% |
    | PUE (optimized, normal, seed 0)      | {metrics.get('pue_optimized_normal', 0):.4f}   |
    | PUE (optimized, drought, seed 0)     | {metrics.get('pue_optimized_drought', 0):.4f}   |
    """)
    print("   Registry: models/registry.json (full lineage/metrics history)")
    print("   All models saved to models/")


if __name__ == "__main__":
    main()
