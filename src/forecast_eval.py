"""Forecaster evaluation against baselines (Task 19 / ML-004). The ONLY place forecaster metrics are computed.

Replaces the single-run, unbaselined RMSE with a protocol-first comparison on simulator data:

* chronological row split (train rows | test rows); a window belongs to a split only if its input rows AND its
  target row are inside that split's rows, so no train window can see a test row (no purge gap needed);
* baselines: persistence, moving average, seasonal-naive (24 h), seasonal-delta, ridge on the same input window;
* learned model (LSTM): >= 5 seeds, one model per evaluated horizon, scored on exactly the same test origins;
* horizon-specific RMSE/MAE with moving-block-bootstrap 95 % intervals, per-regime errors, leakage checks;
* verdict rule fixed in reports/forecast_eval/PROTOCOL.md (paired block bootstrap of RMSE difference).

The metric core is pure NumPy. pandas / scikit-learn / TensorFlow are imported lazily. Everything is about
SIMULATOR data; nothing here says anything about a real facility.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

import numpy as np

PROTOCOL_VERSION = "forecast-eval/1"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "reports" / "forecast_eval"
PROTOCOL_PATH = OUT_DIR / "PROTOCOL.md"

CADENCE_S = 300
SEASON_STEPS = 288  # 24 h at 5 min
SEQ_LEN = 12
MIN_SEEDS = 5
DEFAULT_HORIZONS = (1, 3, 6)
LEARNED_HORIZONS = (6,)
BOOT_BLOCK = 72  # 6 h
BOOT_REPS = 2000
MA_GRID = (3, 6, 12)
RIDGE_GRID = (0.01, 0.1, 1.0, 10.0, 100.0)
BASELINES = ("persistence", "moving_average", "seasonal_naive", "seasonal_delta", "ridge_window")
FEATURES = (
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
)
TARGET = "server_outlet_temp_C"
UTIL = "server_utilisation"


class ForecastEvalError(Exception):
    """A protocol rule was violated (stop condition, not a warning)."""


# ---------------------------------------------------------------------------------------------------------------
# data + split
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Split:
    n_rows: int
    train_end: int  # train rows [0, train_end)
    val_start: int  # validation rows (hyper-parameter choice only) [val_start, train_end)
    seq_len: int = SEQ_LEN

    @property
    def test_start(self) -> int:
        return self.train_end

    def origins(self, which: str, horizon: int) -> np.ndarray:
        """Origin rows t (last input row). Inputs rows t-seq_len+1..t, target row t+horizon, all inside the split."""
        lo, hi = {
            "fit": (0, self.val_start),
            "val": (self.val_start, self.train_end),
            "train": (0, self.train_end),
            "test": (self.train_end, self.n_rows),
        }[which]
        first = lo + self.seq_len - 1
        last = hi - horizon - 1
        return np.arange(first, last + 1, dtype=np.int64) if last >= first else np.empty(0, dtype=np.int64)


def make_split(n_rows: int, train_ratio: float = 0.8, val_ratio: float = 0.2, seq_len: int = SEQ_LEN) -> Split:
    if not 0.5 <= train_ratio < 1:
        raise ForecastEvalError("train_ratio must be in [0.5, 1)")
    train_end = int(n_rows * train_ratio)
    val_start = int(train_end * (1 - val_ratio))
    return Split(n_rows, train_end, val_start, seq_len)


def load_series(path: str | Path):
    """Load the CSV; causal forward-fill only (no back-fill, no outlier removal, no row dropping)."""
    import pandas as pd

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"dataset not found: {p}")
    df = pd.read_csv(p)
    missing = [c for c in (*FEATURES, "timestamp") if c not in df.columns]
    if missing:
        raise ForecastEvalError(f"missing columns: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    step = df["timestamp"].diff().dropna().dt.total_seconds()
    if not (step == CADENCE_S).all():
        raise ForecastEvalError("timestamps are not a gap-free 300 s cadence")
    n_filled = int(df[list(FEATURES)].isna().sum().sum())
    df[list(FEATURES)] = df[list(FEATURES)].ffill()
    if df[list(FEATURES)].isna().any().any():
        raise ForecastEvalError("leading NaN values cannot be forward-filled")
    df.attrs["n_ffilled"] = n_filled
    return df


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def array_hash(a: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(a, dtype=np.float64).tobytes())


def split_hashes(values: np.ndarray, split: Split) -> dict[str, str]:
    return {
        "train_rows": array_hash(values[: split.train_end]),
        "fit_rows": array_hash(values[: split.val_start]),
        "val_rows": array_hash(values[split.val_start : split.train_end]),
        "test_rows": array_hash(values[split.train_end :]),
    }


def windows(x: np.ndarray, origins: np.ndarray, seq_len: int = SEQ_LEN) -> np.ndarray:
    idx = origins[:, None] + np.arange(-seq_len + 1, 1)[None, :]
    return x[idx]


# ---------------------------------------------------------------------------------------------------------------
# baselines (each uses only rows <= origin)
# ---------------------------------------------------------------------------------------------------------------
def predict_persistence(y: np.ndarray, o: np.ndarray, h: int, **_: Any) -> np.ndarray:
    return y[o]


def predict_moving_average(y: np.ndarray, o: np.ndarray, h: int, *, window: int, **_: Any) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(y)])
    return (c[o + 1] - c[o + 1 - window]) / window


def predict_seasonal_naive(y: np.ndarray, o: np.ndarray, h: int, **_: Any) -> np.ndarray:
    if h > SEASON_STEPS:
        raise ForecastEvalError("horizon exceeds the season length")
    idx = o + h - SEASON_STEPS
    if (idx < 0).any():
        raise ForecastEvalError("not enough history for seasonal-naive")
    return y[idx]


def predict_seasonal_delta(y: np.ndarray, o: np.ndarray, h: int, **_: Any) -> np.ndarray:
    idx = o + h - SEASON_STEPS
    if (idx - h < 0).any():
        raise ForecastEvalError("not enough history for seasonal-delta")
    return y[o] + (y[idx] - y[idx - h])


_PREDICTORS = {
    "persistence": predict_persistence,
    "moving_average": predict_moving_average,
    "seasonal_naive": predict_seasonal_naive,
    "seasonal_delta": predict_seasonal_delta,
}


@dataclass
class RidgeWindow:
    """Linear model on the same 12 x 10 window the LSTM sees; scaler and weights fitted on training rows only."""

    alpha: float
    mean: np.ndarray
    std: np.ndarray
    coef: np.ndarray
    intercept: float

    @classmethod
    def fit(cls, feats: np.ndarray, y: np.ndarray, origins: np.ndarray, h: int, alpha: float, fit_rows: int):
        mean = feats[:fit_rows].mean(axis=0)
        std = feats[:fit_rows].std(axis=0)
        std = np.where(std > 0, std, 1.0)
        X = windows((feats - mean) / std, origins).reshape(len(origins), -1)
        t = y[origins + h]
        xm, tm = X.mean(axis=0), t.mean()
        Xc = X - xm
        coef = np.linalg.solve(Xc.T @ Xc + alpha * np.eye(Xc.shape[1]), Xc.T @ (t - tm))
        return cls(alpha, mean, std, coef, float(tm - xm @ coef))

    def predict(self, feats: np.ndarray, origins: np.ndarray) -> np.ndarray:
        X = windows((feats - self.mean) / self.std, origins).reshape(len(origins), -1)
        return X @ self.coef + self.intercept


def rmse(e: np.ndarray) -> float:
    return float(np.sqrt(np.mean(e**2)))


def mae(e: np.ndarray) -> float:
    return float(np.mean(np.abs(e)))


def fit_baselines(
    feats: np.ndarray, y: np.ndarray, split: Split, h: int
) -> dict[str, Callable[[np.ndarray], np.ndarray]]:
    """Choose hyper-parameters on the validation rows only, refit on all training rows. Returns origin -> prediction."""
    val_o = split.origins("val", h)
    val_t = y[val_o + h]
    best_w = min(MA_GRID, key=lambda w: rmse(predict_moving_average(y, val_o, h, window=w) - val_t))
    fit_o = split.origins("fit", h)
    best_a = min(
        RIDGE_GRID,
        key=lambda a: rmse(RidgeWindow.fit(feats, y, fit_o, h, a, split.val_start).predict(feats, val_o) - val_t),
    )
    ridge = RidgeWindow.fit(feats, y, split.origins("train", h), h, best_a, split.train_end)
    return {
        "persistence": lambda o: predict_persistence(y, o, h),
        "moving_average": lambda o: predict_moving_average(y, o, h, window=best_w),
        "seasonal_naive": lambda o: predict_seasonal_naive(y, o, h),
        "seasonal_delta": lambda o: predict_seasonal_delta(y, o, h),
        "ridge_window": lambda o: ridge.predict(feats, o),
        "_chosen": {"moving_average_window": best_w, "ridge_alpha": best_a},  # type: ignore[dict-item]
    }


# ---------------------------------------------------------------------------------------------------------------
# bootstrap + regimes
# ---------------------------------------------------------------------------------------------------------------
def block_indices(n: int, block: int, reps: int, rng: np.random.Generator) -> np.ndarray:
    """(reps, n) moving-block bootstrap indices; blocks keep the autocorrelation of the errors."""
    block = max(1, min(block, n))
    nb = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :n]
    return idx


def _ci(v: np.ndarray) -> list[float]:
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def boot_rmse_ci(e: np.ndarray, idx: np.ndarray) -> list[float]:
    return _ci(np.sqrt((e[idx] ** 2).mean(axis=1)))


def boot_mae_ci(e: np.ndarray, idx: np.ndarray) -> list[float]:
    return _ci(np.abs(e[idx]).mean(axis=1))


def paired_delta_ci(model_errs: Sequence[np.ndarray], base_err: np.ndarray, idx: np.ndarray) -> list[float]:
    """95 % interval of RMSE(model, mean over seeds) - RMSE(baseline) on identical resampled blocks."""
    d = np.mean([np.sqrt((m[idx] ** 2).mean(axis=1)) for m in model_errs], axis=0) - np.sqrt(
        (base_err[idx] ** 2).mean(axis=1)
    )
    return _ci(d)


def verdict(delta_ci: Optional[Sequence[float]]) -> str:
    if delta_ci is None:
        return "unevaluated"
    if delta_ci[1] < 0:
        return "model_better"
    if delta_ci[0] > 0:
        return "model_worse"
    return "inconclusive"


def regimes(feats: np.ndarray, split: Split, origins: np.ndarray) -> dict[str, np.ndarray]:
    """Input-derived regimes; thresholds come from training rows only."""
    u = feats[:, FEATURES.index(UTIL)]
    lo, hi = np.quantile(u[: split.train_end], [1 / 3, 2 / 3])
    ramp = np.abs(u - np.roll(u, 3))
    ramp_thr = float(np.quantile(ramp[3 : split.train_end], 0.75))
    ut, rt = u[origins], ramp[origins]
    return {
        "utilisation_low": ut <= lo,
        "utilisation_mid": (ut > lo) & (ut <= hi),
        "utilisation_high": ut > hi,
        "ramping": rt > ramp_thr,
        "steady": rt <= ramp_thr,
    }


# ---------------------------------------------------------------------------------------------------------------
# learned model
# ---------------------------------------------------------------------------------------------------------------
class Learner(Protocol):
    name: str

    def fit_predict(
        self, x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray, *, seed: int, horizon: int
    ) -> np.ndarray: ...


@dataclass
class TensorFlowLearner:
    """The registered LSTM recipe (src.lstm_model.ThermalForecaster). Needs TensorFlow; never run by the unit tests."""

    epochs: int = 30
    patience: int = 8
    batch_size: int = 32
    name: str = "lstm"

    def fit_predict(self, x_train, y_train, x_test, *, seed, horizon):
        from .lstm_model import ThermalForecaster, _get_tf

        tf = _get_tf()
        tf.keras.utils.set_random_seed(seed)
        fc = ThermalForecaster(verbose=0)
        fc.train(x_train, y_train, epochs=self.epochs, batch_size=self.batch_size, patience=self.patience)
        pred, _, _ = fc.evaluate(
            x_test, np.zeros(len(x_test), dtype=np.float32)
        )  # targets unused; errors recomputed here
        return np.asarray(pred, dtype=np.float64)

    def config(self) -> dict[str, Any]:
        return {
            "epochs": self.epochs,
            "patience": self.patience,
            "batch_size": self.batch_size,
            "validation_split": 0.2,
        }


def tensorflow_status() -> tuple[bool, str]:
    try:
        import tensorflow as tf  # noqa: F401

        return True, str(tf.__version__)
    except Exception as exc:  # ImportError or a broken install
        return False, type(exc).__name__


# ---------------------------------------------------------------------------------------------------------------
# leakage checks
# ---------------------------------------------------------------------------------------------------------------
def leakage_checks(
    feats: np.ndarray, y: np.ndarray, split: Split, horizons: Sequence[int], *, seed: int = 0
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # 1. row disjointness
    ok, worst = True, 0
    for h in horizons:
        tr, te = split.origins("train", h), split.origins("test", h)
        max_train_row = int(tr.max() + h)
        min_test_row = int(te.min() - split.seq_len + 1)
        ok &= max_train_row < min_test_row
        worst = max(worst, max_train_row - min_test_row)
    out.append(
        {
            "name": "train_windows_never_touch_test_rows",
            "passed": bool(ok),
            "detail": f"max train row - min test row <= {worst}",
        }
    )
    # 2. scaler statistics come from training rows only
    fit_mean = feats[: split.train_end].mean(axis=0)
    all_mean = feats.mean(axis=0)
    rm = RidgeWindow.fit(feats, y, split.origins("train", horizons[0]), horizons[0], 1.0, split.train_end)
    out.append(
        {
            "name": "scaler_fitted_on_train_rows_only",
            "passed": bool(np.allclose(rm.mean, fit_mean) and not np.allclose(rm.mean, all_mean)),
            "detail": "scaler mean equals the training-row mean and differs from the all-row mean",
        }
    )
    # 3. causality: scrambling every row after the origin never changes a prediction
    rng = np.random.default_rng(seed)
    bad: list[str] = []
    for h in horizons:
        funcs = fit_baselines(feats, y, split, h)
        for t in rng.choice(split.origins("test", h), size=5, replace=False):
            f2, y2 = feats.copy(), y.copy()
            f2[t + 1 :] = rng.normal(size=f2[t + 1 :].shape) * 1e3
            y2[t + 1 :] = rng.normal(size=y2[t + 1 :].shape) * 1e3
            # seasonal baselines read rows t+h-288 <= t, so scrambling > t must not matter
            for name in ("persistence", "moving_average", "seasonal_naive", "seasonal_delta"):
                f_scr = _PREDICTORS[name]
                kw = {"window": funcs["_chosen"]["moving_average_window"]} if name == "moving_average" else {}  # type: ignore[index]
                a = f_scr(y, np.array([t]), h, **kw)
                b = f_scr(y2, np.array([t]), h, **kw)
                if not np.allclose(a, b):
                    bad.append(f"{name}@h{h}")
            wa = windows(feats, np.array([t]))
            wb = windows(f2, np.array([t]))
            if not np.array_equal(wa, wb):
                bad.append(f"window@h{h}")
    out.append(
        {
            "name": "predictions_ignore_rows_after_the_origin",
            "passed": not bad,
            "detail": "scrambled all rows after 5 sampled origins per horizon"
            + (f"; changed: {sorted(set(bad))}" if bad else ""),
        }
    )
    # 4. documented deviation, not a pass/fail
    out.append(
        {
            "name": "no_outlier_row_removal",
            "passed": True,
            "detail": "rows are never dropped (the legacy pipeline removed rows with whole-file statistics)",
        }
    )
    return out


# ---------------------------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class RunConfig:
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    learned_horizons: tuple[int, ...] = LEARNED_HORIZONS
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    train_ratio: float = 0.8
    boot_reps: int = BOOT_REPS
    boot_block: int = BOOT_BLOCK
    boot_seed: int = 20261021
    physics_version: str = "unrecorded"


def run_evaluation(
    feats: np.ndarray,
    y: np.ndarray,
    cfg: RunConfig,
    *,
    learner: Optional[Learner] = None,
    dataset: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    if learner is not None and len(cfg.seeds) < MIN_SEEDS:
        raise ForecastEvalError(f"a learned model needs at least {MIN_SEEDS} seeds")
    if not set(cfg.learned_horizons) <= set(cfg.horizons):
        raise ForecastEvalError("learned horizons must be evaluated horizons")
    split = make_split(len(y), cfg.train_ratio)
    scaled_min, scaled_max = feats[: split.train_end].min(axis=0), feats[: split.train_end].max(axis=0)
    span = np.where(scaled_max > scaled_min, scaled_max - scaled_min, 1.0)
    rng = np.random.default_rng(cfg.boot_seed)
    res: dict[str, Any] = {}
    for h in cfg.horizons:
        o_te = split.origins("test", h)
        truth = y[o_te + h]
        funcs = fit_baselines(feats, y, split, h)
        chosen = funcs.pop("_chosen")
        idx = block_indices(len(o_te), cfg.boot_block, cfg.boot_reps, rng)
        reg = regimes(feats, split, o_te)
        models: dict[str, Any] = {}
        errs: dict[str, np.ndarray] = {}
        for name in BASELINES:
            e = funcs[name](o_te) - truth  # type: ignore[operator]
            errs[name] = e
            models[name] = {
                "kind": "baseline",
                "rmse": rmse(e),
                "mae": mae(e),
                "rmse_ci95": boot_rmse_ci(e, idx),
                "mae_ci95": boot_mae_ci(e, idx),
            }
        best = min(BASELINES, key=lambda n: models[n]["rmse"])
        entry: dict[str, Any] = {
            "n_test_windows": int(len(o_te)),
            "baseline_choices": chosen,
            "models": models,
            "best_baseline": best,
        }
        if learner is not None and h in cfg.learned_horizons:
            sc_tr = (feats - scaled_min) / span
            o_tr = split.origins("train", h)
            x_tr, y_tr = windows(sc_tr, o_tr).astype(np.float32), y[o_tr + h].astype(np.float32)
            x_te = windows(sc_tr, o_te).astype(np.float32)
            seed_errs, seed_rows = [], []
            for s in cfg.seeds:
                e = np.asarray(learner.fit_predict(x_tr, y_tr, x_te, seed=s, horizon=h), dtype=np.float64) - truth
                seed_errs.append(e)
                seed_rows.append({"seed": s, "rmse": rmse(e), "mae": mae(e)})
            r = np.array([x["rmse"] for x in seed_rows])
            m = np.array([x["mae"] for x in seed_rows])
            dci = paired_delta_ci(seed_errs, errs[best], idx)
            entry["models"][learner.name] = {
                "kind": "learned",
                "seeds": seed_rows,
                "rmse_mean": float(r.mean()),
                "rmse_std": float(r.std(ddof=1)),
                "rmse_min": float(r.min()),
                "rmse_max": float(r.max()),
                "mae_mean": float(m.mean()),
                "rmse_ci95_median_seed": boot_rmse_ci(seed_errs[int(np.argsort(r)[len(r) // 2])], idx),
                "rmse_ci95_note": "block-bootstrap interval of the median-seed model's RMSE",
            }
            entry["paired_delta_rmse_vs_best_baseline"] = {
                "baseline": best,
                "ci95": dci,
                "point": float(r.mean() - models[best]["rmse"]),
            }
            entry["verdict"] = verdict(dci)
            entry["by_regime"] = {
                k: {
                    "n": int(mask.sum()),
                    **{b: {"rmse": rmse(errs[b][mask])} for b in BASELINES if mask.any()},
                    learner.name: {"rmse_mean_over_seeds": float(np.mean([rmse(e[mask]) for e in seed_errs]))}
                    if mask.any()
                    else {},
                }
                for k, mask in reg.items()
            }
        else:
            entry["verdict"] = "unevaluated" if h in cfg.learned_horizons else "baselines_only"
            entry["by_regime"] = {
                k: {"n": int(m_.sum()), **{b: {"rmse": rmse(errs[b][m_])} for b in BASELINES if m_.any()}}
                for k, m_ in reg.items()
            }
        res[str(h)] = entry
    values = np.column_stack([feats, y])
    ok, tf_version = tensorflow_status()
    protocol = PROTOCOL_PATH.read_bytes() if PROTOCOL_PATH.exists() else b""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": sha256_bytes(protocol) if protocol else None,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "simulator data only; says nothing about real hardware",
        "dataset": dict(dataset or {}),
        "split": {
            "n_rows": split.n_rows,
            "train_end": split.train_end,
            "val_start": split.val_start,
            "seq_len": split.seq_len,
            "hashes": split_hashes(values, split),
        },
        "config": {
            "horizons": list(cfg.horizons),
            "learned_horizons": list(cfg.learned_horizons),
            "seeds": list(cfg.seeds) if learner else [],
            "bootstrap": {"reps": cfg.boot_reps, "block_rows": cfg.boot_block, "seed": cfg.boot_seed},
            "learner": getattr(learner, "config", lambda: {})() if learner else None,
            "physics_version_claimed": cfg.physics_version,
        },
        "learned_model_status": (
            "evaluated" if learner else ("not_run: tensorflow_unavailable" if not ok else "not_run: not requested")
        ),
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
            "tensorflow": tf_version if ok else None,
        },
        "leakage_checks": leakage_checks(feats, y, split, cfg.horizons),
        "horizons": res,
    }


def render_report(r: Mapping[str, Any]) -> str:
    L = [
        "# Forecaster evaluation",
        "",
        f"Protocol `{r['protocol_version']}`, simulator data only. Learned model: **{r['learned_model_status']}**.",
        "",
    ]
    for h, e in r["horizons"].items():
        L += [
            f"## Horizon {h} steps ({int(h) * 5} min) — {e['n_test_windows']} held-out windows — verdict: `{e['verdict']}`",
            "",
            "| model | RMSE °C | 95 % interval | MAE °C |",
            "|---|---|---|---|",
        ]
        for n, m in e["models"].items():
            if m["kind"] == "baseline":
                L.append(
                    f"| {n} | {m['rmse']:.4f} | {m['rmse_ci95'][0]:.4f}–{m['rmse_ci95'][1]:.4f} | {m['mae']:.4f} |"
                )
            else:
                L.append(
                    f"| {n} (mean of {len(m['seeds'])} seeds, sd {m['rmse_std']:.4f}) | {m['rmse_mean']:.4f} | seed range {m['rmse_min']:.4f}–{m['rmse_max']:.4f} | {m['mae_mean']:.4f} |"
                )
        d = e.get("paired_delta_rmse_vs_best_baseline")
        if d:
            L += [
                "",
                f"Paired RMSE difference (model − {d['baseline']}): {d['point']:+.4f} °C, 95 % interval {d['ci95'][0]:+.4f} to {d['ci95'][1]:+.4f}.",
            ]
        L.append("")
    L += ["## Leakage checks", ""] + [
        f"- {'PASS' if c['passed'] else 'FAIL'} `{c['name']}`: {c['detail']}" for c in r["leakage_checks"]
    ]
    return "\n".join(L) + "\n"


def card_evidence(r: Mapping[str, Any], results_rel: str = "reports/forecast_eval/results.json") -> str:
    """EVIDENCE lines (tests/test_task31_model_cards.py format) for the cells a card may quote."""
    lines = []
    for h, e in r["horizons"].items():
        for n, m in e["models"].items():
            key = "rmse" if m["kind"] == "baseline" else "rmse_mean"
            lines.append(f"- EVIDENCE h{h}_{n}_rmse = {m[key]!r} | {results_rel} | horizons.{h}.models.{n}.{key}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m src.forecast_eval", description="Task 19 forecaster-vs-baselines evaluation"
    )
    ap.add_argument("--csv", default=str(REPO_ROOT / "data" / "raw" / "sensor_data.csv"))
    ap.add_argument("--generate", action="store_true", help="generate the CSV with src.data_generator if it is missing")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--data-seed", type=int, default=42)
    ap.add_argument("--allow-synthetic-weather", action="store_true")
    ap.add_argument("--allow-synthetic-water-stress", action="store_true")
    ap.add_argument("--physics-version", default="unrecorded")
    ap.add_argument("--seeds", type=int, default=MIN_SEEDS)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--baselines-only", action="store_true")
    ap.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args(argv)

    csv_path = Path(a.csv)
    synthetic: list[str] = []
    gen_version = None
    if not csv_path.exists():
        if not a.generate:
            print(
                f"dataset missing: {csv_path} (pass --generate to create one with src.data_generator)", file=sys.stderr
            )
            return 2
        from .data_generator import GENERATOR_VERSION, generate_sensor_data

        df0 = generate_sensor_data(
            days=a.days,
            seed=a.data_seed,
            allow_synthetic_weather=a.allow_synthetic_weather,
            allow_synthetic_water_stress=a.allow_synthetic_water_stress,
        )
        synthetic = list(df0.attrs.get("synthetic_inputs", []))
        gen_version = GENERATOR_VERSION
        if a.physics_version == "unrecorded":
            a.physics_version = str(df0.attrs.get("physics_version", "unrecorded"))
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df0.to_csv(csv_path, index=False)
    df = load_series(csv_path)
    feats = df[list(FEATURES)].to_numpy(dtype=np.float64)
    y = df[TARGET].to_numpy(dtype=np.float64)
    dataset = {
        "path": csv_path.name,
        "sha256": sha256_bytes(csv_path.read_bytes()),
        "rows": len(df),
        "generator_version": gen_version,
        "synthetic_inputs": synthetic,
        "n_forward_filled_cells": df.attrs.get("n_ffilled", 0),
    }

    learner: Optional[Learner] = None
    if not a.baselines_only:
        ok, why = tensorflow_status()
        if not ok:
            print(
                f"TensorFlow unavailable ({why}); running baselines only. The learned model is NOT evaluated.",
                file=sys.stderr,
            )
        else:
            learner = TensorFlowLearner(epochs=a.epochs)
    cfg = RunConfig(seeds=tuple(range(a.seeds)), physics_version=a.physics_version)
    r = run_evaluation(feats, y, cfg, learner=learner, dataset=dataset)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(r, indent=2, sort_keys=True), encoding="utf-8")
    (out / "REPORT.md").write_text(render_report(r), encoding="utf-8")
    (out / "CARD_EVIDENCE.txt").write_text(card_evidence(r), encoding="utf-8")
    print(render_report(r))
    return 0 if all(c["passed"] for c in r["leakage_checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
