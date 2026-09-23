#!/usr/bin/env python3
"""
Train the predictive-maintenance RUL model on the NASA C-MAPSS FD001 proxy
dataset. See src/predictive_maintenance/__init__.py for why this is a
proxy dataset, not real data-centre hardware data.

Always reports the naive baseline before the LSTM (Part 12 of the master
roadmap: "always establish a simple baseline before a sophisticated
model") -- if the LSTM doesn't clearly beat it, that's a real result to
report, not something to hide.

Usage:
    python -m src.predictive_maintenance.train
    python -m src.predictive_maintenance.train --subset FD001 --window 30 --epochs 50
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from .data_loader import CMAPSSDataset, build_windows
from .model import RULPredictor, evaluate, naive_baseline_predict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = REPO_ROOT / "models" / "predictive_maintenance"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", default="FD001", choices=["FD001", "FD002", "FD003", "FD004"])
    parser.add_argument("--window", type=int, default=30)
    parser.add_argument("--epochs", type=int, default=50)
    args = parser.parse_args()

    print(
        "\nNOTE: this model is trained on NASA C-MAPSS -- a run-to-failure "
        "degradation PROXY dataset (aircraft turbofan engines), used because "
        "no public data-centre-hardware failure dataset exists. Predictions "
        "from this model validate the methodology, not measured data-centre "
        "equipment behaviour.\n"
    )

    dataset = CMAPSSDataset(subset=args.subset)
    data = dataset.load()
    train_df, test_df = data["train"], data["test"]
    test_final_rul, feature_cols = data["test_final_rul"], data["feature_cols"]
    logger.info("Using %d features: %s", len(feature_cols), feature_cols)

    X_train, y_train = build_windows(train_df, feature_cols, window=args.window, label_col="RUL")
    X_test, _ = build_windows(test_df, feature_cols, window=args.window, label_col=None)

    # Random 90/10 split for validation. A chronological-within-engine
    # split would be more rigorous; documenting this as a baseline-stage
    # simplification rather than silently presenting it as best practice.
    n_val = int(0.1 * len(X_train))
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X_train))
    val_idx, train_idx = idx[:n_val], idx[n_val:]
    X_val, y_val = X_train[val_idx], y_train[val_idx]
    X_train, y_train = X_train[train_idx], y_train[train_idx]

    baseline_pred = naive_baseline_predict(y_train, n_test_units=len(test_final_rul))
    baseline_metrics = evaluate(test_final_rul, baseline_pred)
    print(f"Naive baseline (predict median training RUL for every engine): {baseline_metrics}")

    predictor = RULPredictor(n_features=len(feature_cols), window=args.window)
    predictor.train(X_train, y_train, X_val, y_val, epochs=args.epochs, checkpoint_dir=MODEL_DIR)

    lstm_pred = predictor.predict(X_test)
    lstm_metrics = evaluate(test_final_rul, lstm_pred)
    print(f"LSTM RUL model: {lstm_metrics}")

    improvement = (baseline_metrics["mae"] - lstm_metrics["mae"]) / baseline_metrics["mae"] * 100
    print(f"\nMAE improvement over baseline: {improvement:.1f}%")
    if improvement <= 0:
        print(
            "WARNING: LSTM did not beat the naive baseline. Report this "
            "honestly -- do not present the LSTM as the recommended model "
            "until this is investigated."
        )
    predictor.save(MODEL_DIR / "rul_model.keras")
    print(f"\nSaved model to {MODEL_DIR / 'rul_model.keras'}")

    import json
    from datetime import datetime, timezone

    metrics_path = MODEL_DIR / "metrics.json"
    metrics_path.write_text(json.dumps({
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "subset": args.subset,
        "baseline": baseline_metrics,
        "lstm": lstm_metrics,
        "mae_improvement_pct": improvement,
        "beats_baseline": improvement > 0,
        "dataset_caveat": (
            "Trained on NASA C-MAPSS -- a run-to-failure degradation PROXY dataset "
            "(aircraft turbofan engines), used because no public data-centre-hardware "
            "failure dataset exists. These metrics validate the RUL-prediction "
            "methodology, not measured data-centre equipment behaviour."
        ),
    }, indent=2))
    print(f"Saved metrics to {metrics_path}")

if __name__ == "__main__":
    main()  