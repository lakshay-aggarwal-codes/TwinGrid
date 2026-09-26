"""
LSTM Autoencoder anomaly detector for data centre sensors.

Detects anomalies via reconstruction error. Trained only on normal data (anomaly==0).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .logging_config import log_error, log_function_entry, log_function_exit, log_training_progress

logger = logging.getLogger(__name__)

# Lazy imports
_tf = None
_keras = None
_sklearn = None
_joblib = None


def _get_tf():
    global _tf
    if _tf is None:
        try:
            import tensorflow as tf
            _tf = tf
        except ImportError as e:
            raise ImportError("TensorFlow required. pip install tensorflow") from e
    return _tf


def _get_keras():
    return _get_tf().keras


def _get_sklearn():
    global _sklearn
    if _sklearn is None:
        try:
            from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
            from sklearn.preprocessing import MinMaxScaler
            _sklearn = {
                "MinMaxScaler": MinMaxScaler,
                "precision_score": precision_score,
                "recall_score": recall_score,
                "f1_score": f1_score,
                "confusion_matrix": confusion_matrix,
            }
        except ImportError as e:
            raise ImportError("scikit-learn required. pip install scikit-learn") from e
    return _sklearn


def _get_joblib():
    global _joblib
    if _joblib is None:
        try:
            import joblib
            _joblib = joblib
        except ImportError as e:
            raise ImportError("joblib required. pip install joblib") from e
    return _joblib


# Feature columns for anomaly detection (5 features)
FEATURE_COLUMNS = [
    "water_flow_lpm",
    "water_pressure_bar",
    "server_outlet_temp_C",
    "it_power_kw",
    "humidity_pct",
]
SEQ_LEN = 12
N_FEATURES = 5
INPUT_SHAPE = (SEQ_LEN, N_FEATURES)


class AnomalyDetectorError(Exception):
    """Base exception for AnomalyDetector."""

    pass


class NotTrainedError(AnomalyDetectorError):
    """Raised when detector is used before training."""

    pass


class ShapeError(AnomalyDetectorError, ValueError):
    """Raised when input sequences don't have shape (n, seq_len, 5).

    Also a ValueError, so callers that already catch ValueError keep working.
    """

    pass


class AnomalyDetector:
    """
    LSTM Autoencoder for anomaly detection on data centre sensor sequences.

    Encoder: LSTM(32) → LSTM(8) [bottleneck]
    Decoder: RepeatVector(12) → LSTM(8) → LSTM(32) → TimeDistributed(Dense(5))
    Trained only on normal data. Threshold = 95th percentile of training errors.
    """

    def __init__(
        self,
        *,
        seq_len: int = SEQ_LEN,
        feature_columns: list[str] | None = None,
        percentile: float = 95.0,
        verbose: int = 1,
    ) -> None:
        """
        Initialise the anomaly detector.

        Args:
            seq_len: Sequence length (default: 12).
            feature_columns: Columns to use (default: 5 sensor cols).
            percentile: Percentile for threshold (default: 95).
            verbose: Keras verbosity.
        """
        self._seq_len = seq_len
        self._feature_columns = feature_columns or FEATURE_COLUMNS.copy()
        self._percentile = percentile
        self._verbose = verbose
        self._model: Any = None
        self._scaler: Any = None
        self._threshold: float | None = None
        self._is_trained = False

    @property
    def threshold(self) -> float | None:
        """The 95th-percentile reconstruction-error threshold learned during
        training. None if the detector hasn't been trained/loaded yet.
        Exposed so callers (e.g. the API layer) can report anomaly scores
        as a fraction of this real, model-derived value, rather than an
        arbitrary display scale.
        """
        return self._threshold

    def _build_model(self) -> Any:
        """Build LSTM autoencoder."""
        keras = _get_keras()
        K = keras

        encoder_input = K.layers.Input(shape=(self._seq_len, N_FEATURES), name="encoder_input")
        x = K.layers.LSTM(32, return_sequences=True, name="lstm_enc_1")(encoder_input)
        x = K.layers.LSTM(8, return_sequences=False, name="lstm_enc_2")(x)  # bottleneck

        repeat = K.layers.RepeatVector(self._seq_len, name="repeat")(x)
        x = K.layers.LSTM(8, return_sequences=True, name="lstm_dec_1")(repeat)
        x = K.layers.LSTM(32, return_sequences=True, name="lstm_dec_2")(x)
        decoder_output = K.layers.TimeDistributed(
            K.layers.Dense(N_FEATURES, name="dense_output")
        )(x)

        model = K.Model(encoder_input, decoder_output, name="lstm_autoencoder")
        model.compile(optimizer="adam", loss="mse")
        return model

    def _create_sequences(self, data: np.ndarray) -> np.ndarray:
        """Create sliding window sequences (seq_len, n_features)."""
        sequences = []
        for i in range(len(data) - self._seq_len + 1):
            sequences.append(data[i : i + self._seq_len])
        return np.array(sequences, dtype=np.float32)

    def sequences_from_df(self, df: pd.DataFrame) -> np.ndarray:
        """
        Create sequences from DataFrame for detection or evaluation.

        Args:
            df: DataFrame with feature columns.

        Returns:
            Sequences of shape (n, seq_len, 5).
        """
        seqs, _ = self._prepare_data(df, normal_only=False)
        return seqs

    def _prepare_data(
        self,
        df: pd.DataFrame,
        *,
        normal_only: bool = False,
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """
        Create sequences and optionally filter by anomaly label.

        Returns:
            (sequences, labels) where labels is None if normal_only or no anomaly col.
        """
        missing = set(self._feature_columns) - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        if normal_only and "anomaly" in df.columns:
            df = df[df["anomaly"] == 0].reset_index(drop=True)
            logger.info("Filtered to %d normal rows", len(df))

        data = df[self._feature_columns].values.astype(np.float32)
        sequences = self._create_sequences(data)

        labels = None
        if "anomaly" in df.columns:
            # Label: 1 if any anomaly in the sequence window
            labels = np.zeros(len(sequences), dtype=np.int32)
            for i in range(len(sequences)):
                start = i
                end = i + self._seq_len
                if df["anomaly"].iloc[start:end].max() > 0:
                    labels[i] = 1

        return sequences, labels

    def train(
        self,
        df: pd.DataFrame,
        *,
        epochs: int = 50,
        batch_size: int = 32,
        validation_split: float = 0.2,
        patience: int = 10,
    ) -> dict[str, Any]:
        """
        Train on normal data only (anomaly==0 rows).

        Args:
            df: DataFrame with feature columns and anomaly column.
            epochs: Max epochs.
            batch_size: Batch size.
            validation_split: Validation fraction.
            patience: Early stopping patience.

        Returns:
            Training history dict.
        """
        log_function_entry(
            "AnomalyDetector.train",
            df_shape=df.shape,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            patience=patience
        )
        
        try:
            MinMaxScaler = _get_sklearn()["MinMaxScaler"]

            sequences, _ = self._prepare_data(df, normal_only=True)
            if len(sequences) == 0:
                error_msg = "No normal sequences found."
                log_error("AnomalyDetector.train", ValueError(error_msg))
                raise ValueError(error_msg)

            self._scaler = MinMaxScaler()
            sequences_scaled = self._scaler.fit_transform(
                sequences.reshape(-1, N_FEATURES)
            ).reshape(sequences.shape)

            if self._model is None:
                self._model = self._build_model()

            # Create custom callback for training progress logging
            class TrainingProgressCallback(_get_keras().callbacks.Callback):
                def on_epoch_end(self, epoch, logs=None):
                    logs = logs or {}
                    log_training_progress(
                        "AnomalyDetector",
                        epoch=epoch + 1,
                        loss=logs.get('loss', 0),
                        val_loss=logs.get('val_loss', 0)
                    )

            keras = _get_keras()
            K = keras
            history = self._model.fit(
                sequences_scaled,
                sequences_scaled,  # Autoencoder: reconstruct input
                epochs=epochs,
                batch_size=batch_size,
                validation_split=validation_split,
                callbacks=[
                    K.callbacks.EarlyStopping(
                        monitor="val_loss",
                        patience=patience,
                        restore_best_weights=True,
                        verbose=1,
                    ),
                    TrainingProgressCallback(),
                ],
                verbose=self._verbose,
            )

            # Compute reconstruction errors and set threshold
            reconstructions = self._model.predict(sequences_scaled, verbose=0)
            errors = np.mean((sequences_scaled - reconstructions) ** 2, axis=(1, 2))
            self._threshold = float(np.percentile(errors, self._percentile))
            self._is_trained = True

            logger.info(
                "Training complete. Threshold (%.0fth percentile): %.6f",
                self._percentile,
                self._threshold,
            )
            
            log_function_exit("AnomalyDetector.train", result=f"Training completed with threshold: {self._threshold:.6f}")
            return dict(history.history)
        except Exception as e:
            log_error("AnomalyDetector.train", e)
            raise

    def _compute_errors(self, sequences: np.ndarray) -> np.ndarray:
        """Compute reconstruction MSE per sample."""
        if self._scaler is None:
            raise NotTrainedError("Detector must be trained first.")
        sequences_scaled = self._scaler.transform(
            sequences.reshape(-1, N_FEATURES)
        ).reshape(sequences.shape)
        reconstructions = self._model.predict(sequences_scaled, verbose=0)
        return np.mean((sequences_scaled - reconstructions) ** 2, axis=(1, 2))

    def detect(
        self,
        sequences: np.ndarray,
        *,
        threshold: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect anomalies from reconstruction error.

        Args:
            sequences: Shape (n_samples, 12, 5) — raw feature values.
            threshold: Override stored threshold if provided.

        Returns:
            (error_scores, boolean_alerts) where alert=True if error > threshold.
        """
        if not self._is_trained or self._model is None:
            raise NotTrainedError("Detector must be trained before detection.")

        thresh = threshold if threshold is not None else self._threshold
        if thresh is None:
            raise NotTrainedError("Threshold not set. Train or load first.")

        if sequences.ndim != 3 or sequences.shape[1] != self._seq_len or sequences.shape[2] != N_FEATURES:
            raise ShapeError(
                f"sequences must be (n, {self._seq_len}, {N_FEATURES}), got {sequences.shape}"
            )

        error_scores = self._compute_errors(sequences)
        alerts = error_scores > thresh
        return error_scores.astype(np.float32), alerts.astype(bool)

    def evaluate(
        self,
        df: pd.DataFrame,
    ) -> dict[str, Any]:
        """
        Evaluate on DataFrame with anomaly labels.

        Args:
            df: DataFrame with feature columns and anomaly column.

        Returns:
            Dict with precision, recall, F1, confusion_matrix.
        """
        if not self._is_trained:
            raise NotTrainedError("Detector must be trained before evaluation.")

        sequences, labels = self._prepare_data(df, normal_only=False)
        if labels is None:
            raise ValueError("DataFrame must have 'anomaly' column for evaluation.")

        _, alerts = self.detect(sequences)
        labels = labels.astype(bool)

        sk = _get_sklearn()
        precision = float(sk["precision_score"](labels, alerts, zero_division=0))
        recall = float(sk["recall_score"](labels, alerts, zero_division=0))
        f1 = float(sk["f1_score"](labels, alerts, zero_division=0))
        cm = sk["confusion_matrix"](labels, alerts)

        result = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "confusion_matrix": cm.tolist(),
        }
        logger.info("Evaluation: P=%.4f R=%.4f F1=%.4f", precision, recall, f1)
        return result

    def save(self, path: str | Path) -> None:
        """
        Save model, scaler, and threshold to directory.

        Args:
            path: Directory path (creates model.keras, scaler.joblib, config.json).
        """
        if not self._is_trained:
            raise NotTrainedError("Detector must be trained before saving.")

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        self._model.save(str(path / "model.keras"))
        _get_joblib().dump(self._scaler, path / "scaler.joblib")
        (path / "config.json").write_text(
            json.dumps({
                "threshold": self._threshold,
                "seq_len": self._seq_len,
                "feature_columns": self._feature_columns,
                "percentile": self._percentile,
            }, indent=2)
        )
        logger.info("Saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> AnomalyDetector:
        """
        Load model, scaler, and threshold from directory.

        Args:
            path: Directory containing model.keras, scaler.joblib, config.json.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        keras = _get_keras()
        joblib = _get_joblib()

        config = json.loads((path / "config.json").read_text())
        detector = cls(
            seq_len=config.get("seq_len", SEQ_LEN),
            feature_columns=config.get("feature_columns", FEATURE_COLUMNS),
            percentile=config.get("percentile", 95.0),
        )
        detector._model = keras.models.load_model(str(path / "model.keras"))
        detector._scaler = joblib.load(path / "scaler.joblib")
        detector._threshold = config["threshold"]
        detector._is_trained = True

        logger.info("Loaded from %s, threshold=%.6f", path, detector._threshold)
        return detector
