#!/usr/bin/env python3
"""Task 11: naive forecasting baselines on the SAME split, horizon and metric as the thermal forecaster, plus a leakage audit.

The forecaster (``src.lstm_model.ThermalForecaster``) predicts ``server_outlet_temp_C`` 6 steps (30 min) ahead from 12 steps of
history and is scored as RMSE / MAE in degC on the chronological held-out windows. This script scores, on exactly those windows:

* ``persistence``     -- the value now (the outlet temperature at the last input step).
* ``seasonal_naive``  -- the value one season earlier (default 24 h before the target time, found by timestamp; windows whose
  lagged timestamp does not exist are counted and left out, and every method is ALSO scored on that common subset).
* ``train_mean``      -- the mean target of the training windows (a floor, not a competitor).
* ``model``           -- the saved forecaster, only if ``--model-dir`` is given and TensorFlow is installed; otherwise
  ``not_run`` with the reason. Nothing is assumed about the model.

It also reports, from the data actually supplied: whether the file is the one the registry recorded for the forecaster
(SHA-256), the train/test boundary overlap, windows whose time span is not the documented 30 min (rows dropped by the outlier
filter), identical windows shared by both splits, duplicate timestamps, and how much of the labelled anomaly data the pipeline
removed before training.

Nothing here trains anything and nothing is written unless ``--out`` is given. Read-only on the CSV and the registry.

    python scripts/forecast_baselines.py --csv data/raw/sensor_data.csv
    python scripts/forecast_baselines.py --csv data/raw/sensor_data.csv --model-dir models/forecaster --out forecast_baselines.json

Exit status: 0 report produced; 2 bad arguments or an unreadable input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.lstm_model import DataPipeline, WindowSplit  # noqa: E402

METHODS = ("persistence", "seasonal_naive", "train_mean")
REGISTRY_TOLERANCE = 1e-3  # degC: float32 / TensorFlow run-to-run noise allowed when re-scoring the registered model


class InputError(ValueError):
    """The CSV, registry or an argument cannot be used (exit status 2)."""


# ----------------------------------------------------------------------------- metrics and baselines (pure)
def score(pred: np.ndarray, truth: np.ndarray) -> dict[str, Any]:
    """RMSE and MAE in the target's own units (the same arithmetic as ``ThermalForecaster.evaluate``)."""
    pred = np.asarray(pred, dtype=np.float64)
    truth = np.asarray(truth, dtype=np.float64)
    if pred.shape != truth.shape:
        raise ValueError("pred and truth must have the same shape")
    if pred.size == 0:
        return {"n": 0, "rmse": None, "mae": None}
    err = pred - truth
    return {"n": int(pred.size), "rmse": float(np.sqrt(np.mean(err**2))), "mae": float(np.mean(np.abs(err)))}


def persistence_forecast(X_raw: np.ndarray, feature_columns: list[str], target_column: str) -> np.ndarray:
    """The target variable's value at the LAST input step of each window ("same as now")."""
    if target_column not in feature_columns:
        raise InputError(f"persistence needs {target_column!r} among the features {feature_columns}")
    return X_raw[:, -1, feature_columns.index(target_column)].astype(np.float64)


def seasonal_naive_forecast(
    frame: pd.DataFrame, target_rows: np.ndarray, target_column: str, season: pd.Timedelta, time_column: str = "timestamp"
) -> np.ndarray:
    """The target variable one ``season`` before each window's target time, looked up BY TIMESTAMP (rows may have been dropped
    upstream, so a row offset would be wrong). ``nan`` where that timestamp does not exist. Uses only earlier values."""
    if time_column not in frame.columns:
        raise InputError(f"seasonal-naive needs a {time_column!r} column")
    times = pd.DatetimeIndex(frame[time_column])
    if times.has_duplicates:
        raise InputError("seasonal-naive needs unique timestamps (the file has duplicates)")
    series = pd.Series(frame[target_column].to_numpy(dtype=np.float64), index=times)
    lagged = times[target_rows] - season
    return series.reindex(lagged).to_numpy(dtype=np.float64)


def train_mean_forecast(y_train: np.ndarray, n: int) -> np.ndarray:
    return np.full(n, float(np.mean(y_train)), dtype=np.float64)


def window_time_gaps(frame: pd.DataFrame, starts: np.ndarray, seq_len: int, horizon: int, cadence_s: float) -> int:
    """Windows whose first input and target are not exactly ``(seq_len + horizon - 1)`` cadences apart (a row was dropped or
    the series has a gap inside the window, so the target is not the documented horizon ahead)."""
    if len(starts) == 0 or "timestamp" not in frame.columns:
        return 0
    t = pd.DatetimeIndex(frame["timestamp"])
    span = (t[starts + seq_len + horizon - 1] - t[starts]).total_seconds().to_numpy()
    return int(np.sum(~np.isclose(span, (seq_len + horizon - 1) * cadence_s)))


def count_shared_windows(X_a: np.ndarray, X_b: np.ndarray) -> int:
    """Windows with byte-identical inputs present in both arrays (exact duplicates across the splits)."""
    hashes = {hashlib.blake2b(x.tobytes(), digest_size=16).digest() for x in X_a}
    return sum(1 for x in X_b if hashlib.blake2b(x.tobytes(), digest_size=16).digest() in hashes)


def compare(results: dict[str, dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    """Does the model beat persistence? Both RMSE and MAE must be lower, on the same windows. ``None`` if it was not scored."""
    if model.get("status") != "ok":
        return {"model_beats_persistence": None, "reason": model.get("reason", "model not evaluated")}
    p = results["persistence"]
    beats = model["rmse"] < p["rmse"] and model["mae"] < p["mae"]
    return {
        "model_beats_persistence": bool(beats),
        "rmse_change_pct_vs_persistence": 100.0 * (model["rmse"] - p["rmse"]) / p["rmse"],
        "mae_change_pct_vs_persistence": 100.0 * (model["mae"] - p["mae"]) / p["mae"],
    }


# ----------------------------------------------------------------------------- inputs
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def registry_entry(registry_path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    """The newest forecaster entry of the registry, or ``(None, why not)``."""
    if registry_path is None:
        return None, "no registry given"
    if not registry_path.exists():
        return None, f"registry not found: {registry_path}"
    try:
        doc = json.loads(registry_path.read_text(encoding="utf-8"))
        entries = [a for a in doc["artifacts"] if a.get("kind") == "forecaster" or a.get("name") == "forecaster"]
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"registry unreadable ({type(exc).__name__})"
    if not entries:
        return None, "registry has no forecaster entry"
    return max(entries, key=lambda e: str(e.get("created_at_utc", ""))), None


def anomaly_scope(raw: pd.DataFrame, kept: pd.DataFrame, feature_columns: list[str]) -> dict[str, Any] | None:
    """How many labelled anomaly rows the pipeline's outlier filter removed before windowing (None without the label)."""
    if "anomaly" not in raw.columns or "timestamp" not in raw.columns:
        return None
    raw = raw.copy()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"])
    flagged = raw.loc[raw["anomaly"] == 1, "timestamp"]
    removed = int((~flagged.isin(pd.DatetimeIndex(kept["timestamp"]))).sum())
    return {
        "rows_dropped_by_outlier_filter": int(len(raw) - len(kept)),
        "anomaly_rows_in_file": int(len(flagged)),
        "anomaly_rows_removed_before_training": removed,
        "anomaly_rows_removed_share": (removed / len(flagged)) if len(flagged) else None,
    }


def _keep_mask(frame: pd.DataFrame, reference: pd.DataFrame, columns: list[str], k: float) -> pd.Series:
    """The pipeline's rule (``DataPipeline.load_csv``): keep a row if every column is within ``k`` std of ``reference``'s mean."""
    keep = pd.Series(True, index=frame.index)
    for col in columns:
        mean, std = reference[col].mean(), reference[col].std()
        if std > 0:
            keep &= (frame[col] >= mean - k * std) & (frame[col] <= mean + k * std)
    return keep


def outlier_filter_audit(raw: pd.DataFrame, columns: list[str], k: float, train_ratio: float) -> dict[str, Any] | None:
    """How much the outlier filter's decisions depend on the TEST period. The pipeline computes mean/std over the whole file,
    so a row's keep/drop decision can change with rows that come later in time. Compares that with thresholds computed from
    the first ``train_ratio`` of the rows only. ``None`` without a timestamp column. Reports counts; it does not say which is 'right'."""
    if "timestamp" not in raw.columns:
        return None
    ordered = raw.copy()
    ordered["timestamp"] = pd.to_datetime(ordered["timestamp"])
    ordered = ordered.sort_values("timestamp").reset_index(drop=True)
    cols = [c for c in columns if c in ordered.columns]
    cut = int(len(ordered) * train_ratio)
    whole = _keep_mask(ordered, ordered, cols, k)
    train_only = _keep_mask(ordered, ordered.iloc[:cut], cols, k)
    return {
        "rows_with_a_different_decision": int((whole != train_only).sum()),
        "train_rows_with_a_different_decision": int((whole.iloc[:cut] != train_only.iloc[:cut]).sum()),
        "test_rows_dropped_with_whole_file_thresholds": int((~whole.iloc[cut:]).sum()),
        "test_rows_dropped_with_train_only_thresholds": int((~train_only.iloc[cut:]).sum()),
    }


# ----------------------------------------------------------------------------- the model (optional)
def evaluate_model(model_dir: Path, pipe: DataPipeline, split: WindowSplit) -> dict[str, Any]:
    """Score the saved forecaster on the held-out windows, or say exactly why it was not scored. Never raises."""
    try:
        from src.lstm_model import ThermalForecaster

        forecaster = ThermalForecaster.load(model_dir / "thermal.keras")
        pipe.load_scaler(model_dir / "scaler.json")
        scaled = pipe.transform_sequence(split.X_test)
        _, rmse, mae = forecaster.evaluate(scaled, split.y_test)
        return {"status": "ok", "n": int(len(split.y_test)), "rmse": float(rmse), "mae": float(mae)}
    except Exception as exc:  # noqa: BLE001 - report, never crash: a missing TensorFlow is the normal case in CI
        return {"status": "not_run", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


# ----------------------------------------------------------------------------- the report
def run(
    csv_path: Path,
    *,
    seq_len: int = 12,
    horizon: int = 6,
    train_ratio: float = 0.8,
    purge_gap: int = 0,
    season_hours: float = 24.0,
    model_dir: Path | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise InputError(f"CSV not found: {csv_path}")
    if not (season_hours > 0 and math.isfinite(season_hours)):
        raise InputError("season_hours must be positive")

    pipe = DataPipeline(seq_len=seq_len, horizon=horizon, train_ratio=train_ratio, purge_gap=purge_gap)
    try:
        frame = pipe.load_csv(csv_path)
        split = pipe.split_windows()
    except (ValueError, KeyError) as exc:
        raise InputError(str(exc)) from exc
    raw = pd.read_csv(csv_path)

    feature_columns = pipe.feature_columns
    target_rows = split.target_rows(split.test_starts)
    y = split.y_test.astype(np.float64)

    # cadence from the data (median step), not assumed
    times = pd.DatetimeIndex(frame["timestamp"]) if "timestamp" in frame.columns else None
    # unit-independent (pandas >= 3 stores datetimes in microseconds, older versions in nanoseconds)
    cadence_s = float(times.to_series().diff().dt.total_seconds().median()) if times is not None and len(times) > 1 else None

    preds: dict[str, np.ndarray] = {
        "persistence": persistence_forecast(split.X_test, feature_columns, pipe.target_column),
        "train_mean": train_mean_forecast(split.y_train, len(y)),
    }
    seasonal_status: dict[str, Any] = {"status": "ok"}
    try:
        preds["seasonal_naive"] = seasonal_naive_forecast(frame, target_rows, pipe.target_column, pd.Timedelta(hours=season_hours))
    except InputError as exc:
        seasonal_status = {"status": "not_run", "reason": str(exc)}

    all_windows = {name: score(p, y) for name, p in preds.items() if name != "seasonal_naive"}
    common: dict[str, dict[str, Any]] = {}
    coverage = None
    if "seasonal_naive" in preds:
        ok = ~np.isnan(preds["seasonal_naive"])
        coverage = float(ok.mean()) if len(ok) else None
        all_windows["seasonal_naive"] = score(preds["seasonal_naive"][ok], y[ok])  # only where a lagged value exists
        common = {name: score(p[ok], y[ok]) for name, p in preds.items()}

    model = {"status": "not_run", "reason": "no --model-dir given"} if model_dir is None else evaluate_model(model_dir, pipe, split)
    comparison = compare(all_windows, model)

    entry, registry_note = registry_entry(registry_path)
    csv_sha = sha256_file(csv_path)
    recorded = entry.get("dataset_sha256") if entry else None
    matches = None if recorded is None else (csv_sha == recorded)
    registered_metrics = entry.get("metrics") if entry else None
    reproduces = None
    if model.get("status") == "ok" and matches is True and purge_gap == 0 and registered_metrics:
        reproduces = abs(model["rmse"] - registered_metrics["rmse"]) <= REGISTRY_TOLERANCE and abs(model["mae"] - registered_metrics["mae"]) <= REGISTRY_TOLERANCE

    overlap = split.boundary_overlap_rows()
    shared_rows = len(split.rows_touched(split.train_starts) & split.rows_touched(split.test_starts))
    return {
        "script": "scripts/forecast_baselines.py (Task 11)",
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "tensorflow": _tf_version(),
            "platform": platform.system(),
        },
        "data": {
            "csv": str(csv_path),
            "sha256": csv_sha,
            "registry_dataset_sha256": recorded,
            "matches_registry": matches,
            "registry_note": registry_note,
            "rows_after_loading": int(len(frame)),
            "cadence_s": cadence_s,
            "duplicate_timestamps": int(frame["timestamp"].duplicated().sum()) if "timestamp" in frame.columns else None,
        },
        "protocol": {
            "target": pipe.target_column,
            "seq_len": seq_len,
            "horizon_steps": horizon,
            "train_ratio": train_ratio,
            "purge_gap": purge_gap,
            "split_id": pipe.split_id(),
            "season_hours": season_hours,
            "train_windows": int(len(split.y_train)),
            "test_windows": int(len(y)),
            "metric": "RMSE and MAE in degC on the unscaled target (same as ThermalForecaster.evaluate)",
        },
        "audit": {
            "boundary_overlap_rows": overlap,
            "rows_read_by_both_splits": shared_rows,
            "identical_input_windows_in_both_splits": count_shared_windows(split.X_train, split.X_test),
            "test_windows_with_a_time_gap": window_time_gaps(frame, split.test_starts, seq_len, horizon, cadence_s) if cadence_s else None,
            "train_windows_with_a_time_gap": window_time_gaps(frame, split.train_starts, seq_len, horizon, cadence_s) if cadence_s else None,
            "anomaly_scope": anomaly_scope(raw, frame, feature_columns),
            "outlier_filter_dependence_on_test_rows": outlier_filter_audit(raw, feature_columns, pipe.outlier_std, train_ratio),
        },
        "baselines_all_test_windows": all_windows,
        "seasonal_naive": {**seasonal_status, "coverage_of_test_windows": coverage},
        "baselines_common_subset": common,
        "model": model,
        "comparison": comparison,
        "registered_model": {
            "registry_metrics": registered_metrics,
            "model_rescored_matches_registry": reproduces,
        },
        "verdict": _verdict(comparison, model, matches, purge_gap),
    }


def _tf_version() -> str | None:
    try:
        import tensorflow as tf  # noqa: PLC0415

        return str(tf.__version__)
    except Exception:  # noqa: BLE001
        return None


def _verdict(comparison: dict[str, Any], model: dict[str, Any], matches: bool | None, purge_gap: int) -> str:
    if comparison["model_beats_persistence"] is None:
        return f"NOT VERIFIED: the model was not scored ({comparison['reason']}). Baselines above are valid for this CSV only."
    scope = (
        "on the file the registry recorded for the registered model"
        if matches is True and purge_gap == 0
        else "on THIS data, which is not shown to be the registered model's own held-out data (compare data.sha256 with the registry)"
    )
    verb = "beats" if comparison["model_beats_persistence"] else "does NOT beat"
    return f"The model {verb} persistence {scope}: one run, no seeds, no confidence interval."


# ----------------------------------------------------------------------------- CLI
def _print(report: dict[str, Any]) -> None:
    def f(v: Any) -> str:
        return "n/a" if v is None else f"{v:.4f}"

    p = report["protocol"]
    print(f"Task 11 forecast baselines: {report['data']['csv']}")
    print(f"  sha256 {report['data']['sha256'][:16]}...  matches registry: {report['data']['matches_registry']}")
    print(f"  split {p['split_id']}  train windows {p['train_windows']}  test windows {p['test_windows']}  horizon {p['horizon_steps']} steps")
    print(f"  {'method':16s} {'n':>7s} {'RMSE degC':>10s} {'MAE degC':>10s}")
    for name, m in {**report["baselines_all_test_windows"], "model": report["model"]}.items():
        if name == "model" and m.get("status") != "ok":
            print(f"  {'model':16s} {'-':>7s} {'not run':>10s}   ({m.get('reason')})")
            continue
        print(f"  {name:16s} {m['n']:>7d} {f(m['rmse']):>10s} {f(m['mae']):>10s}")
    a = report["audit"]
    print(f"  audit: boundary overlap rows {a['boundary_overlap_rows']}, test windows with a time gap {a['test_windows_with_a_time_gap']}, identical windows in both splits {a['identical_input_windows_in_both_splits']}")
    print(f"  verdict: {report['verdict']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Persistence / seasonal-naive baselines and a leakage audit for the thermal forecaster.")
    ap.add_argument("--csv", type=Path, default=Path("data/raw/sensor_data.csv"))
    ap.add_argument("--seq-len", type=int, default=12)
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--train-ratio", type=float, default=0.8)
    ap.add_argument("--purge-gap", default="0", help="windows dropped between train and test: an integer, or 'auto' (seq_len + horizon - 1)")
    ap.add_argument("--season-hours", type=float, default=24.0)
    ap.add_argument("--model-dir", type=Path, default=None, help="directory with thermal.keras and scaler.json (needs TensorFlow)")
    ap.add_argument("--registry", type=Path, default=Path("models/registry.json"))
    ap.add_argument("--out", type=Path, default=None, help="write the full report as JSON here")
    args = ap.parse_args(argv)
    try:
        gap = (args.seq_len + args.horizon - 1) if args.purge_gap == "auto" else int(args.purge_gap)
        report = run(
            args.csv,
            seq_len=args.seq_len,
            horizon=args.horizon,
            train_ratio=args.train_ratio,
            purge_gap=gap,
            season_hours=args.season_hours,
            model_dir=args.model_dir,
            registry_path=args.registry,
        )
    except (InputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
