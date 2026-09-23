"""
Load and prepare the NASA C-MAPSS Turbofan Degradation dataset for the
predictive-maintenance / Remaining-Useful-Life (RUL) model.

See src/predictive_maintenance/__init__.py for the proxy-dataset caveat
that applies to everything in this module.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..logging_config import log_error, log_function_entry, log_function_exit

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CMAPSS_DIR = REPO_ROOT / "realData" / "CMAPSSData"

_COLUMN_NAMES = (
    ["unit_number", "time_in_cycles", "op_setting_1", "op_setting_2", "op_setting_3"]
    + [f"sensor_{i}" for i in range(1, 22)]
)

# Standard piecewise-linear RUL assumption used throughout the C-MAPSS
# literature: engines run near-healthy for most of their life and degrade
# roughly linearly only close to failure, so raw (max_cycle - current_cycle)
# labels would imply misleadingly precise long-horizon predictions. Capping
# is a documented modeling choice, not an arbitrary number.
DEFAULT_RUL_CAP = 125


class CMAPSSDataset:
    """Loads one C-MAPSS sub-dataset (FD001..FD004), computes RUL labels,
    drops low-variance sensors (data-driven, not a hardcoded index list --
    see module rationale), and scales features using train-set statistics
    only (never fit on test data, to avoid leakage).
    """

    def __init__(self, subset: str = "FD001", rul_cap: int = DEFAULT_RUL_CAP):
        self.subset = subset
        self.rul_cap = rul_cap
        self._feature_cols: list[str] | None = None
        self._scaler_min: pd.Series | None = None
        self._scaler_range: pd.Series | None = None

    def _read_raw(self, path: Path) -> pd.DataFrame:
        # C-MAPSS text files have trailing whitespace on every line, which
        # produces 2 extra all-NaN columns if read naively -- drop them
        # explicitly rather than relying on read_csv to guess correctly.
        df = pd.read_csv(path, sep=r"\s+", header=None)
        df = df.dropna(axis=1, how="all")
        df.columns = _COLUMN_NAMES[: df.shape[1]]
        return df

    def _compute_train_rul(self, train_df: pd.DataFrame) -> pd.DataFrame:
        max_cycle = train_df.groupby("unit_number")["time_in_cycles"].transform("max")
        rul = max_cycle - train_df["time_in_cycles"]
        train_df = train_df.copy()
        train_df["RUL"] = np.minimum(rul, self.rul_cap)
        return train_df

    def _select_features(self, train_df: pd.DataFrame, std_threshold: float = 1e-3) -> list[str]:
        candidate_cols = [c for c in train_df.columns if c.startswith("sensor_") or c.startswith("op_setting_")]
        stds = train_df[candidate_cols].std()
        selected = stds[stds > std_threshold].index.tolist()
        dropped = sorted(set(candidate_cols) - set(selected))
        logger.info("Dropping %d low-variance columns: %s", len(dropped), dropped)
        if not selected:
            raise ValueError("Feature selection dropped every candidate column -- check std_threshold.")
        return selected

    def _fit_scaler(self, train_df: pd.DataFrame) -> None:
        self._scaler_min = train_df[self._feature_cols].min()
        self._scaler_range = (train_df[self._feature_cols].max() - self._scaler_min).replace(0, 1.0)

    def _scale(self, df: pd.DataFrame) -> pd.DataFrame:
        scaled = df.copy()
        scaled[self._feature_cols] = (df[self._feature_cols] - self._scaler_min) / self._scaler_range
        return scaled

    def load(self) -> dict:
        log_function_entry("CMAPSSDataset.load", subset=self.subset)
        try:
            train_path = CMAPSS_DIR / f"train_{self.subset}.txt"
            test_path = CMAPSS_DIR / f"test_{self.subset}.txt"
            rul_path = CMAPSS_DIR / f"RUL_{self.subset}.txt"
            for p in (train_path, test_path, rul_path):
                if not p.exists():
                    raise FileNotFoundError(
                        f"{p} not found. Confirm realData/CMAPSSData/ contains the C-MAPSS "
                        f"files (see data/external/CMAPSSData/provenance.json)."
                    )

            train_df = self._read_raw(train_path)
            test_df = self._read_raw(test_path)
            test_final_rul = pd.read_csv(rul_path, header=None, names=["RUL"])["RUL"].to_numpy()

            train_df = self._compute_train_rul(train_df)
            self._feature_cols = self._select_features(train_df)
            self._fit_scaler(train_df)

            train_scaled = self._scale(train_df)
            test_scaled = self._scale(test_df)

            log_function_exit(
                "CMAPSSDataset.load",
                result=f"{len(train_df)} train rows, {len(test_df)} test rows, {len(self._feature_cols)} features",
            )
            return {
                "train": train_scaled,
                "test": test_scaled,
                "test_final_rul": test_final_rul,
                "feature_cols": self._feature_cols,
            }
        except Exception as e:
            log_error("CMAPSSDataset.load", e)
            raise


def build_windows(
    df: pd.DataFrame,
    feature_cols: list[str],
    window: int = 30,
    label_col: str | None = "RUL",
) -> tuple[np.ndarray, np.ndarray | None]:
    """Build fixed-length sliding windows per engine unit.

    Training data (label_col="RUL"): one window per cycle (sliding),
    labeled with that cycle's RUL.
    Test data (label_col=None): one window per engine, taken from the END
    of its recorded cycles (the point we're asked to predict remaining
    life from), left-padded if the engine has fewer than `window` cycles.
    """
    X, y = [], []
    for _, unit_df in df.groupby("unit_number"):
        unit_df = unit_df.sort_values("time_in_cycles")
        values = unit_df[feature_cols].to_numpy()

        if label_col is not None:
            labels = unit_df[label_col].to_numpy()
            for end in range(window, len(values) + 1):
                X.append(values[end - window : end])
                y.append(labels[end - 1])
        else:
            if len(values) >= window:
                X.append(values[-window:])
            else:
                pad = np.repeat(values[:1], window - len(values), axis=0)
                X.append(np.vstack([pad, values]))

    X_arr = np.array(X, dtype=np.float32)
    y_arr = np.array(y, dtype=np.float32) if label_col is not None else None
    return X_arr, y_arr