"""
LSTM-based thermal forecaster and data pipeline for data centre temperature prediction.

Predicts server_outlet_temp_C 30 minutes ahead from 12 time steps × 10 features.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .logging_config import log_error, log_function_entry, log_function_exit, log_training_progress

logger = logging.getLogger(__name__)

# Lazy imports for optional dependencies
_tf = None
_keras = None
_plt = None
_sklearn = None
_joblib = None


def _get_tf():
    """Lazy import TensorFlow."""
    global _tf
    if _tf is None:
        try:
            import tensorflow as tf
            _tf = tf
        except ImportError as e:
            raise ImportError(
                "TensorFlow is required. Install with: pip install tensorflow"
            ) from e
    return _tf


def _get_keras():
    """Lazy import Keras from TensorFlow."""
    return _get_tf().keras


def _get_plt():
    """Lazy import matplotlib."""
    global _plt
    if _plt is None:
        try:
            import matplotlib.pyplot as plt
            _plt = plt
        except ImportError as e:
            raise ImportError(
                "Matplotlib is required. Install with: pip install matplotlib"
            ) from e
    return _plt


def _get_sklearn():
    """Lazy import sklearn."""
    global _sklearn
    if _sklearn is None:
        try:
            from sklearn.preprocessing import MinMaxScaler
            _sklearn = {"MinMaxScaler": MinMaxScaler}
        except ImportError as e:
            raise ImportError(
                "scikit-learn is required. Install with: pip install scikit-learn"
            ) from e
    return _sklearn


def _get_joblib():
    """Lazy import joblib."""
    global _joblib
    if _joblib is None:
        try:
            import joblib
            _joblib = joblib
        except ImportError as e:
            raise ImportError(
                "joblib is required. Install with: pip install joblib"
            ) from e
    return _joblib


# Dimensions
TIMESTEPS = 12
N_FEATURES = 10
INPUT_SHAPE = (TIMESTEPS, N_FEATURES)
HORIZON = 6  # 6 × 5 min = 30 min

# Default feature columns (must total 10)
DEFAULT_FEATURE_COLUMNS = [
    "server_utilisation",
    "outside_temp_C",
    "server_inlet_temp_C",
    "server_outlet_temp_C",
    "it_power_kw",
    "cooling_power_kw",
    "total_power_kw",
    "pue",
    "water_flow_lpm",
    "humidity_pct",
]
TARGET_COLUMN = "server_outlet_temp_C"


class ThermalForecasterError(Exception):
    """Base exception for ThermalForecaster."""

    pass


class ShapeError(ThermalForecasterError):
    """Raised when input shape is invalid."""

    pass


class NotTrainedError(ThermalForecasterError):
    """Raised when model is used before training."""

    pass


# -----------------------------------------------------------------------------
# DataPipeline
# -----------------------------------------------------------------------------


class DataPipeline:
    """
    Data pipeline for loading, preprocessing, and creating LSTM sequences.

    - Loads CSV, fills nulls, removes outliers (±3 std)
    - Creates sliding windows (seq_len=12, horizon=6 → 30 min prediction)
    - Time-based 80/20 train/test split
    - MinMaxScaler fit on train, transform both
    """

    def __init__(
        self,
        *,
        feature_columns: list[str] | None = None,
        target_column: str = TARGET_COLUMN,
        seq_len: int = 12,
        horizon: int = 6,
        train_ratio: float = 0.8,
        outlier_std: float = 3.0,
    ) -> None:
        """
        Initialise the data pipeline.

        Args:
            feature_columns: Columns to use as features (default: 10 sensor cols).
            target_column: Column to predict (default: server_outlet_temp_C).
            seq_len: Input sequence length (default: 12).
            horizon: Steps ahead to predict (default: 6 → 30 min).
            train_ratio: Fraction for train split (default: 0.8).
            outlier_std: Std threshold for outlier removal (default: 3).
        """
        self._feature_columns = feature_columns or DEFAULT_FEATURE_COLUMNS.copy()
        self._target_column = target_column
        self._seq_len = seq_len
        self._horizon = horizon
        self._train_ratio = train_ratio
        self._outlier_std = outlier_std
        self._scaler: Any = None
        self._df: pd.DataFrame | None = None

    def load_csv(self, path: str | Path) -> pd.DataFrame:
        """
        Load CSV, parse timestamp, fill nulls, remove outliers.

        Args:
            path: Path to CSV file.

        Returns:
            Preprocessed DataFrame.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")

        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)

        # Fill nulls with forward then backward fill
        df = df.ffill().bfill()

        # Remove outliers (±3 std) on feature columns only (not target/anomaly)
        cols_to_check = [c for c in self._feature_columns if c in df.columns]
        mask = pd.Series(True, index=df.index)
        for col in cols_to_check:
            mean, std = df[col].mean(), df[col].std()
            if std > 0:
                mask &= (df[col] >= mean - self._outlier_std * std) & (
                    df[col] <= mean + self._outlier_std * std
                )
        df = df[mask]

        self._df = df.reset_index(drop=True)
        logger.info("Loaded %d rows from %s", len(self._df), path)
        return self._df

    def _create_sequences(self, data: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Create sliding window sequences."""
        X_list, y_list = [], []
        for i in range(len(data) - self._seq_len - self._horizon + 1):
            X_list.append(data[i : i + self._seq_len])
            y_list.append(target[i + self._seq_len + self._horizon - 1])
        return np.array(X_list, dtype=np.float32), np.array(y_list, dtype=np.float32)

    def prepare(
        self,
        df: pd.DataFrame | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Create sequences and perform time-based train/test split with scaling.

        Args:
            df: DataFrame to use. If None, uses last loaded df.

        Returns:
            (X_train, y_train, X_test, y_test) as numpy arrays.
        """
        df = df or self._df
        if df is None:
            raise ValueError("No data loaded. Call load_csv() first.")

        # Ensure all columns exist
        required = set(self._feature_columns) | {self._target_column}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        data = df[self._feature_columns].values.astype(np.float32)
        target = df[self._target_column].values.astype(np.float32)

        # Time-based split
        n = len(data) - self._seq_len - self._horizon + 1
        if n <= 0:
            raise ValueError(
                f"Not enough data for seq_len={self._seq_len}, horizon={self._horizon}"
            )
        split_idx = int(n * self._train_ratio)

        # Create sequences for full data first
        X, y = self._create_sequences(data, target)

        # Split
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        # Scale
        MinMaxScaler = _get_sklearn()["MinMaxScaler"]
        self._scaler = MinMaxScaler()
        # Reshape for scaler: (n, seq, feat) -> (n*seq, feat)
        n_train, seq_len, n_feat = X_train.shape
        X_train_flat = X_train.reshape(-1, n_feat)
        self._scaler.fit(X_train_flat)
        X_train = self._scaler.transform(X_train_flat).reshape(n_train, seq_len, n_feat)
        X_test = self._scaler.transform(X_test.reshape(-1, n_feat)).reshape(
            X_test.shape[0], seq_len, n_feat
        )

        logger.info(
            "Prepared X_train %s, y_train %s, X_test %s, y_test %s",
            X_train.shape, y_train.shape, X_test.shape, y_test.shape,
        )
        return X_train, y_train, X_test, y_test

    def save_scaler(self, path: str | Path) -> None:
        """Save fitted scaler with joblib."""
        if self._scaler is None:
            raise ValueError("Scaler not fitted. Call prepare() first.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib = _get_joblib()
        joblib.dump(self._scaler, path)
        logger.info("Scaler saved to %s", path)

    def load_scaler(self, path: str | Path) -> None:
        """Load scaler from joblib."""
        joblib = _get_joblib()
        self._scaler = joblib.load(path)
        logger.info("Scaler loaded from %s", path)

    def transform_sequence(self, sequence: np.ndarray) -> np.ndarray:
        """
        Transform a raw sequence for prediction (scale to match training).

        Args:
            sequence: Shape (12, 10) or (1, 12, 10) — raw feature values.

        Returns:
            Scaled sequence ready for predict_next_30min().
        """
        if self._scaler is None:
            raise ValueError("Scaler not fitted. Call prepare() first.")
        arr = np.asarray(sequence, dtype=np.float32)
        orig_shape = arr.shape
        arr = self._scaler.transform(arr.reshape(-1, orig_shape[-1]))
        return arr.reshape(orig_shape).astype(np.float32)

    @property
    def scaler(self):
        """Fitted MinMaxScaler (or None)."""
        return self._scaler

    @property
    def feature_columns(self) -> list[str]:
        """Feature column names."""
        return self._feature_columns


# -----------------------------------------------------------------------------
# ThermalForecaster
# -----------------------------------------------------------------------------


class ThermalForecaster:
    """
    LSTM forecaster for server_outlet_temp_C 30 minutes ahead.

    Architecture: LSTM(64) → Dropout(0.2) → LSTM(32) → Dropout(0.2)
                 → Dense(16, relu) → Dense(1)
    Input: (12, 10) — 12 steps × 10 features
    Output: predicted server_outlet_temp_C in 30 min
    """

    def __init__(
        self,
        *,
        input_shape: tuple[int, int] = INPUT_SHAPE,
        verbose: int = 1,
    ) -> None:
        """
        Initialise the ThermalForecaster.

        Args:
            input_shape: (timesteps, features) — default (12, 10).
            verbose: Keras verbosity.
        """
        self._input_shape = input_shape
        self._verbose = verbose
        self._model: Any = None
        self._history: Any = None
        self._is_trained = False

    def _build_model(self) -> Any:
        """Build the LSTM model."""
        keras = _get_keras()
        K = keras

        model = K.Sequential(
            [
                K.layers.Input(shape=self._input_shape),
                K.layers.LSTM(64, return_sequences=True, name="lstm_1"),
                K.layers.Dropout(0.2, name="dropout_1"),
                K.layers.LSTM(32, return_sequences=False, name="lstm_2"),
                K.layers.Dropout(0.2, name="dropout_2"),
                K.layers.Dense(16, activation="relu", name="dense_1"),
                K.layers.Dense(1, name="output"),
            ],
            name="thermal_forecaster",
        )
        model.compile(optimizer="adam", loss="mse", metrics=["mae"])
        return model

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        *,
        epochs: int = 50,
        batch_size: int = 32,
        validation_split: float = 0.2,
        patience: int = 10,
        checkpoint_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Train the model with early stopping and model checkpoint.

        Args:
            X_train: Shape (n_samples, 12, 10).
            y_train: Shape (n_samples,).
            epochs: Max epochs.
            batch_size: Batch size.
            validation_split: Validation fraction.
            patience: Early stopping patience.
            checkpoint_dir: Where to save best model.

        Returns:
            Training history dict.
        """
        log_function_entry(
            "ThermalForecaster.train",
            X_train_shape=X_train.shape,
            y_train_shape=y_train.shape,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            patience=patience,
            checkpoint_dir=checkpoint_dir
        )
        
        try:
            if X_train.ndim != 3 or X_train.shape[1:] != self._input_shape:
                error_msg = f"X_train must be (n, 12, 10), got {X_train.shape}"
                log_error("ThermalForecaster.train", ShapeError(error_msg))
                raise ShapeError(error_msg)
            if y_train.ndim != 1 or len(y_train) != len(X_train):
                error_msg = f"y_train shape mismatch: {y_train.shape}"
                log_error("ThermalForecaster.train", ShapeError(error_msg))
                raise ShapeError(error_msg)

            keras = _get_keras()
            K = keras

            if self._model is None:
                self._model = self._build_model()

            # Create custom callback for training progress logging
            class TrainingProgressCallback(K.callbacks.Callback):
                def on_epoch_end(self, epoch, logs=None):
                    logs = logs or {}
                    log_training_progress(
                        "ThermalForecaster",
                        epoch=epoch + 1,
                        loss=logs.get('loss', 0),
                        val_loss=logs.get('val_loss', 0),
                        mae=logs.get('mae', 0),
                        val_mae=logs.get('val_mae', 0)
                    )

            callbacks: list[Any] = [
                K.callbacks.EarlyStopping(
                    monitor="val_loss",
                    patience=patience,
                    restore_best_weights=True,
                    verbose=1,
                ),
                TrainingProgressCallback(),
            ]
            if checkpoint_dir:
                ckpt_path = Path(checkpoint_dir) / "best_thermal_forecaster.keras"
                ckpt_path.parent.mkdir(parents=True, exist_ok=True)
                callbacks.append(
                    K.callbacks.ModelCheckpoint(
                        str(ckpt_path),
                        monitor="val_loss",
                        save_best_only=True,
                        verbose=1,
                    )
                )

            history = self._model.fit(
                X_train,
                y_train,
                epochs=epochs,
                batch_size=batch_size,
                validation_split=validation_split,
                callbacks=callbacks,
                verbose=self._verbose,
            )
            self._history = history.history
            self._is_trained = True
            
            best_val_loss = min(history.history["val_loss"])
            logger.info("Training complete. Best val_loss: %.6f", best_val_loss)
            
            log_function_exit("ThermalForecaster.train", result=f"Training completed with best val_loss: {best_val_loss:.6f}")
            return dict(self._history)
        except Exception as e:
            log_error("ThermalForecaster.train", e)
            raise

    def evaluate(
        self,
        X_test: np.ndarray,
        y_test: np.ndarray,
    ) -> tuple[np.ndarray, float, float]:
        """
        Evaluate on test set.

        Args:
            X_test: Test sequences (n, 12, 10).
            y_test: Test targets (n,).

        Returns:
            (predictions, rmse, mae).
        """
        if not self._is_trained or self._model is None:
            raise NotTrainedError("Model must be trained before evaluation")

        predictions = self._model.predict(X_test, verbose=0).flatten()
        mse = np.mean((predictions - y_test) ** 2)
        rmse = float(np.sqrt(mse))
        mae = float(np.mean(np.abs(predictions - y_test)))
        logger.info("Evaluation: RMSE=%.4f, MAE=%.4f", rmse, mae)
        return predictions, rmse, mae

    def predict_next_30min(self, sequence: np.ndarray) -> float:
        """
        Predict server_outlet_temp_C 30 min ahead from a sequence.

        Args:
            sequence: Shape (12, 10) or (1, 12, 10).

        Returns:
            Predicted temperature (°C).
        """
        if not self._is_trained or self._model is None:
            raise NotTrainedError("Model must be trained before prediction")

        X = np.asarray(sequence, dtype=np.float32)
        if X.ndim == 2:
            if X.shape != self._input_shape:
                raise ShapeError(f"sequence shape must be (12, 10), got {X.shape}")
            X = np.expand_dims(X, axis=0)
        elif X.ndim == 3:
            X = X[:1]
        else:
            raise ShapeError(f"sequence must be 2D or 3D, got ndim={X.ndim}")

        pred = self._model.predict(X, verbose=0)
        return float(pred[0, 0])

    def save(self, path: str | Path) -> None:
        """Save model to disk."""
        if not self._is_trained or self._model is None:
            raise NotTrainedError("Model must be trained before saving")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._model.save(str(path))
        logger.info("Model saved to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> ThermalForecaster:
        """Load model from disk."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found: {path}")
        keras = _get_keras()
        forecaster = cls()
        forecaster._model = keras.models.load_model(str(path))
        forecaster._is_trained = True
        forecaster._input_shape = forecaster._model.input_shape[1:]
        logger.info("Model loaded from %s", path)
        return forecaster

    def plot_training_curves(
        self,
        save_path: str | Path | None = None,
        figsize: tuple[float, float] = (10, 4),
    ) -> None:
        """Plot training loss and MAE curves."""
        if self._history is None:
            raise NotTrainedError("Model must be trained before plotting")

        plt = _get_plt()
        fig, axes = plt.subplots(1, 2, figsize=figsize)
        epochs = range(1, len(self._history["loss"]) + 1)

        axes[0].plot(epochs, self._history["loss"], label="Train Loss")
        axes[0].plot(epochs, self._history["val_loss"], label="Val Loss")
        axes[0].set_xlabel("Epoch")
        axes[0].set_ylabel("Loss (MSE)")
        axes[0].set_title("Training and Validation Loss")
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)

        axes[1].plot(epochs, self._history["mae"], label="Train MAE")
        axes[1].plot(epochs, self._history["val_mae"], label="Val MAE")
        axes[1].set_xlabel("Epoch")
        axes[1].set_ylabel("MAE (°C)")
        axes[1].set_title("Training and Validation MAE")
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Training curves saved to %s", save_path)
        plt.show()
