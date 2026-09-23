#!/usr/bin/env python3
"""
Validate the anomaly-detection METHODOLOGY (LSTM autoencoder, trained on
normal data only, alerting via a reconstruction-error threshold) against
real, human-labeled anomalies from the Numenta Anomaly Benchmark (NAB).

IMPORTANT -- what this script does and does NOT do:
The production AnomalyDetector (src/anomaly_detector.py) is trained on 5
data-centre-specific features (water flow, water pressure, outlet temp, IT
power, humidity) and is NOT retrained or modified by this script. NAB's
real-world series have a different feature space entirely (often a single
sensor channel), so there is no valid way to feed NAB data directly into
that 5-feature model.

Instead, this script builds a SEPARATE autoencoder with the same
architecture and training discipline, sized for NAB's univariate series,
and evaluates it against NAB's real ground-truth anomaly windows. This
validates that the DETECTION APPROACH generalizes to real, human-labeled
anomalies -- it does not, and cannot, validate the production model's
numbers on real data-centre hardware, because that data does not exist.

Usage:
    python -m src.anomaly_detector_nab_validation
    python -m src.anomaly_detector_nab_validation --file realKnownCause/machine_temperature_system_failure.csv
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
NAB_DATA_DIR = REPO_ROOT / "realData" / "NAB-master" / "data"
NAB_LABELS_PATH = REPO_ROOT / "realData" / "NAB-master" / "labels" / "combined_windows.json"

SEQ_LEN = 12  # matches AnomalyDetector.SEQ_LEN -- like-for-like methodology comparison
PERCENTILE = 95.0  # matches AnomalyDetector's default threshold percentile


def _build_univariate_autoencoder(seq_len: int = SEQ_LEN):
    """Same architecture pattern as AnomalyDetector._build_model, sized for
    1 feature instead of 5 -- see module docstring for why this is a
    separate model, not the production one.
    """
    from tensorflow import keras as K

    encoder_input = K.layers.Input(shape=(seq_len, 1), name="encoder_input")
    x = K.layers.LSTM(32, return_sequences=True, name="lstm_enc_1")(encoder_input)
    x = K.layers.LSTM(8, return_sequences=False, name="lstm_enc_2")(x)
    repeat = K.layers.RepeatVector(seq_len, name="repeat")(x)
    x = K.layers.LSTM(8, return_sequences=True, name="lstm_dec_1")(repeat)
    x = K.layers.LSTM(32, return_sequences=True, name="lstm_dec_2")(x)
    decoder_output = K.layers.TimeDistributed(K.layers.Dense(1), name="dense_output")(x)
    model = K.Model(encoder_input, decoder_output, name="nab_univariate_autoencoder")
    model.compile(optimizer="adam", loss="mse")
    return model


def _load_nab_windows(relative_path: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if not NAB_LABELS_PATH.exists():
        raise FileNotFoundError(
            f"{NAB_LABELS_PATH} not found. Confirm realData/NAB-master/labels/combined_windows.json "
            f"is present (see data/external/NAB-master/provenance.json)."
        )
    with open(NAB_LABELS_PATH) as f:
        all_windows = json.load(f)

    if relative_path in all_windows:
        raw_windows = all_windows[relative_path]
    else:
        filename = Path(relative_path).name
        matches = [k for k in all_windows if Path(k).name == filename]
        if not matches:
            raise KeyError(
                f"No labeled windows found for '{relative_path}' in {NAB_LABELS_PATH}. "
                f"Available keys (sample): {list(all_windows.keys())[:5]}"
            )
        raw_windows = all_windows[matches[0]]

    return [(pd.Timestamp(start), pd.Timestamp(end)) for start, end in raw_windows]


def _build_windows(values: np.ndarray, seq_len: int) -> np.ndarray:
    return np.array(
        [values[i : i + seq_len] for i in range(len(values) - seq_len + 1)],
        dtype=np.float32,
    )


def validate(relative_path: str = "realKnownCause/machine_temperature_system_failure.csv") -> dict:
    csv_path = NAB_DATA_DIR / relative_path
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Confirm realData/NAB-master/data/{relative_path} exists."
        )

    df = pd.read_csv(csv_path, parse_dates=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    windows = _load_nab_windows(relative_path)
    logger.info("Loaded %d rows, %d labeled anomaly windows for %s", len(df), len(windows), relative_path)

    df["is_anomaly"] = 0
    for start, end in windows:
        df.loc[(df["timestamp"] >= start) & (df["timestamp"] <= end), "is_anomaly"] = 1

    # Train on the normal-only PREFIX of the series, strictly before the
    # first labeled anomaly -- mirrors AnomalyDetector's own "train on
    # normal data only" discipline, and avoids leaking future-anomaly
    # information into training that a real deployment would never have.
    first_anomaly_start = min(w[0] for w in windows)
    train_df = df[df["timestamp"] < first_anomaly_start]
    if len(train_df) < SEQ_LEN * 5:
        raise ValueError(
            f"Only {len(train_df)} normal rows before the first labeled anomaly -- "
            f"too little to train a meaningful autoencoder. Choose a different NAB file."
        )
    logger.info("Training on %d normal rows before first labeled anomaly at %s", len(train_df), first_anomaly_start)

    from sklearn.metrics import f1_score, precision_score, recall_score
    from sklearn.preprocessing import MinMaxScaler
    from tensorflow import keras as K

    scaler = MinMaxScaler()
    train_values = scaler.fit_transform(train_df[["value"]]).flatten()
    all_values = scaler.transform(df[["value"]]).flatten()

    train_windows = _build_windows(train_values, SEQ_LEN).reshape(-1, SEQ_LEN, 1)
    all_windows_arr = _build_windows(all_values, SEQ_LEN).reshape(-1, SEQ_LEN, 1)

    model = _build_univariate_autoencoder()
    model.fit(
        train_windows, train_windows,
        epochs=30, batch_size=32, validation_split=0.1,
        callbacks=[K.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)],
        verbose=0,
    )

    train_recon = model.predict(train_windows, verbose=0)
    train_errors = np.mean((train_windows - train_recon) ** 2, axis=(1, 2))
    threshold = float(np.percentile(train_errors, PERCENTILE))

    all_recon = model.predict(all_windows_arr, verbose=0)
    all_errors = np.mean((all_windows_arr - all_recon) ** 2, axis=(1, 2))
    predicted = (all_errors > threshold).astype(int)

    # Ground truth per window: 1 if ANY row in that window is inside a
    # labeled anomaly -- same "window contains an anomaly" convention
    # AnomalyDetector._prepare_data uses for the production model.
    true_labels = np.array(
        [df["is_anomaly"].iloc[i : i + SEQ_LEN].max() for i in range(len(df) - SEQ_LEN + 1)]
    )

    return {
        "threshold": threshold,
        "precision": float(precision_score(true_labels, predicted, zero_division=0)),
        "recall": float(recall_score(true_labels, predicted, zero_division=0)),
        "f1": float(f1_score(true_labels, predicted, zero_division=0)),
        "n_windows_evaluated": int(len(true_labels)),
        "n_true_anomalous_windows": int(true_labels.sum()),
        "n_predicted_anomalous_windows": int(predicted.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        default="realKnownCause/machine_temperature_system_failure.csv",
        help="Path relative to realData/NAB-master/data/",
    )
    args = parser.parse_args()

    print(
        "\nNOTE: this validates the anomaly-detection METHODOLOGY against real, "
        "human-labeled anomalies (NAB). It trains a separate, matching-architecture "
        "model sized for NAB's data -- it does NOT modify or retrain the production "
        "5-feature data-centre AnomalyDetector, since no real data-centre failure "
        "labels exist to validate that model against directly.\n"
    )

    metrics = validate(args.file)
    print(f"NAB validation results for {args.file}:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()