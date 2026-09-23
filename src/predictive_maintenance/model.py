"""
Remaining-Useful-Life (RUL) prediction model. See
src/predictive_maintenance/__init__.py for the proxy-dataset caveat.

Architecture mirrors src/lstm_model.py's ThermalForecaster (stacked LSTM ->
dropout -> dense) deliberately, so this codebase has one consistent
sequence-model style rather than a second one invented for this module.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ..logging_config import log_error, log_function_entry, log_function_exit, log_training_progress

logger = logging.getLogger(__name__)


class RULModelError(Exception):
    pass


class NotTrainedError(RULModelError):
    pass


def naive_baseline_predict(train_rul: np.ndarray, n_test_units: int) -> np.ndarray:
    """Baseline: predict the median training RUL for every test engine,
    ignoring its actual sensor readings entirely. If the LSTM below doesn't
    clearly beat this, the LSTM isn't earning its added complexity --
    train.py reports both, always.
    """
    median_rul = float(np.median(train_rul))
    return np.full(n_test_units, median_rul, dtype=np.float32)


class RULPredictor:
    """Stacked-LSTM Remaining-Useful-Life regressor."""

    def __init__(self, n_features: int, window: int = 30):
        self.n_features = n_features
        self.window = window
        self._model: Any = None

    def _build_model(self):
        from tensorflow import keras as K

        model = K.Sequential(
            [
                K.layers.Input(shape=(self.window, self.n_features)),
                K.layers.LSTM(64, return_sequences=True),
                K.layers.Dropout(0.2),
                K.layers.LSTM(32),
                K.layers.Dropout(0.2),
                K.layers.Dense(16, activation="relu"),
                K.layers.Dense(1),
            ]
        )
        model.compile(optimizer=K.optimizers.Adam(learning_rate=0.001), loss="mse", metrics=["mae"])
        return model

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        epochs: int = 50,
        batch_size: int = 64,
        checkpoint_dir: str | Path | None = None,
    ):
        log_function_entry("RULPredictor.train", n_samples=len(X_train))
        try:
            from tensorflow import keras as K

            self._model = self._build_model()
            monitor = "val_loss" if X_val is not None else "loss"
            callbacks = [K.callbacks.EarlyStopping(monitor=monitor, patience=10, restore_best_weights=True)]
            if checkpoint_dir is not None:
                Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)
                ckpt_path = Path(checkpoint_dir) / "rul_model.keras"
                callbacks.append(K.callbacks.ModelCheckpoint(str(ckpt_path), save_best_only=True))

            validation_data = (X_val, y_val) if X_val is not None else None
            history = self._model.fit(
                X_train, y_train,
                validation_data=validation_data,
                epochs=epochs, batch_size=batch_size,
                callbacks=callbacks, verbose=0,
            )
            log_training_progress(
                "RULPredictor", epochs=len(history.history["loss"]), final_loss=history.history["loss"][-1]
            )
            log_function_exit("RULPredictor.train", result="trained")
            return history
        except Exception as e:
            log_error("RULPredictor.train", e)
            raise

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise NotTrainedError("Call train() or load() before predict().")
        return self._model.predict(X, verbose=0).flatten()

    def save(self, path: str | Path) -> None:
        if self._model is None:
            raise NotTrainedError("Nothing to save -- model has not been trained.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._model.save(path)

    @classmethod
    def load(cls, path: str | Path, n_features: int, window: int = 30) -> "RULPredictor":
        from tensorflow import keras as K

        instance = cls(n_features=n_features, window=window)
        instance._model = K.models.load_model(Path(path))
        return instance


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """MAE, RMSE, R^2 reported together -- RUL models commonly over- or
    under-predict asymmetrically (late maintenance vs. wasted early
    maintenance), which a single metric can hide.
    """
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = r2_score(y_true, y_pred)
    return {"mae": float(mae), "rmse": rmse, "r2": float(r2)}