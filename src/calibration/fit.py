"""Calibration of physics v2 against facility telemetry: split, fit, identifiability, one-shot test (Task 23).

Procedure (docs/tasks/Task23_calibration_REPORT.md):
  1. Split in TIME (contiguous fit / validation / test blocks), written into a pre-registration with its hash.
  2. Fit the eligible parameters by bounded least squares (log-scaled Levenberg-Marquardt). The only model
     option, a ridge pull toward the published values, is chosen on the VALIDATION block.
  3. Identifiability check on the fit block (Jacobian sensitivity, correlation, bounds). Parameters the data
     cannot pin down are returned to their published values, listed as "not identified", and the rest refit.
  4. Score the TEST block exactly once, for the fitted model, the published-parameter model and a persistence
     predictor. A second read raises ``TestBlockAlreadyScored``.
  5. The fit is called an improvement only if it beats BOTH nulls on EVERY pre-registered metric.
  6. Optional block bootstrap over days for parameter intervals.

Not done here: profile likelihood (a Jacobian approximation is used instead), short-gap interpolation, and
fitting ``tau_chw_min`` / ``chw_rate_limit_c_per_5min`` (they need a measured supply-temperature channel).
Every other PhysicsParams field keeps its published value.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Optional

import numpy as np

from src.physics import v2
from src.physics.params import DEFAULT_PHYSICS_PARAMS, MODES, PhysicsParams, PhysicsParamsError

from .data import INPUT_CHANNELS, OUTPUT_CHANNELS, CalibrationData

_MODES_SET = frozenset(MODES)

SCHEMA = "twingrid-calibration/1"
PENALTY = 1.0e3

# name -> (lo, hi, modes that must be present (None = any row)). Bounds are physical limits, not priors.
SPECS: dict[str, tuple[float, float, Optional[tuple[str, ...]]]] = {
    "max_it_power_kw": (50.0, 5000.0, None),
    "idle_power_fraction": (0.05, 0.9, None),
    "thermal_capacitance_kj_per_k": (2000.0, 500000.0, None),
    "coil_ua_kw_per_k": (2.0, 400.0, None),
    "tau_air_min": (1.0, 60.0, None),
    "chw_approach_c": (0.1, 6.0, ("closed_loop", "evaporative", "hybrid")),
    "cop_free_air": (1.5, 12.0, ("free_air",)),
    "cop_closed_loop": (1.5, 12.0, ("closed_loop",)),
    "cop_evaporative": (1.5, 12.0, ("evaporative",)),
    "cop_hybrid": (1.5, 12.0, ("hybrid",)),
}
METRICS_ALL = ("t_in_c", "t_out_c", "cooling_power_kw", "pue")


class CalibrationError(ValueError):
    """The calibration cannot proceed as pre-registered."""


class TestBlockAlreadyScored(CalibrationError):
    """The test block is read once. A second score would turn it into a second validation block."""

    __test__ = False  # not a pytest class


# ------------------------------------------------------------------------------------------------ segments
@dataclass
class Segment:
    day: int
    util: np.ndarray
    temp: np.ndarray
    hum: np.ndarray
    chw: np.ndarray
    mode: list[str]
    obs: dict[str, np.ndarray]  # nan where not observed; includes derived "pue"


def _segments(data: CalibrationData, i0: int, i1: int, min_steps: int) -> list[Segment]:
    usable = np.ones(data.n_rows, dtype=bool)
    for ch in INPUT_CHANNELS:
        usable &= data.observed[ch]
    usable &= np.array([m in _MODES_SET for m in data.mode])
    days = data.ts.astype("datetime64[D]").astype(np.int64)
    out: list[Segment] = []
    i = i0
    while i < i1:
        if not usable[i]:
            i += 1
            continue
        j = i
        while j + 1 < i1 and usable[j + 1] and days[j + 1] == days[i]:
            j += 1
        if j - i + 1 >= min_steps:
            sl = slice(i, j + 1)
            obs = {ch: np.where(data.observed[ch][sl], data.values[ch][sl], np.nan) for ch in OUTPUT_CHANNELS}
            with np.errstate(divide="ignore", invalid="ignore"):
                obs["pue"] = np.where(
                    obs["it_power_kw"] > 0, (obs["it_power_kw"] + obs["cooling_power_kw"]) / obs["it_power_kw"], np.nan
                )
            out.append(
                Segment(
                    day=int(days[i]),
                    util=data.values["utilisation"][sl],
                    temp=data.values["outside_temp_c"][sl],
                    hum=data.values["humidity_pct"][sl],
                    chw=data.values["chw_requested_c"][sl],
                    mode=[str(m) for m in data.mode[sl]],
                    obs=obs,
                )
            )
        i = j + 1
    return out


def simulate(params: PhysicsParams, seg: Segment, dt_s: float) -> dict[str, np.ndarray]:
    n = len(seg.util)
    first = v2.StepInputs(float(seg.util[0]), float(seg.temp[0]), float(seg.hum[0]), seg.mode[0], float(seg.chw[0]))
    state = v2.initial_state(first, params, float(seg.chw[0]))
    it = np.empty(n)
    t_in = np.empty(n)
    t_out = np.empty(n)
    cool = np.empty(n)
    for k in range(n):
        res = v2.step(
            state,
            v2.StepInputs(float(seg.util[k]), float(seg.temp[k]), float(seg.hum[k]), seg.mode[k], float(seg.chw[k])),
            dt_s,
            params,
        )
        state = res.state
        it[k], t_in[k], t_out[k], cool[k] = res.it_power_kw, state.t_in_c, state.t_out_c, res.cooling_electrical_kw
    return {"it_power_kw": it, "t_in_c": t_in, "t_out_c": t_out, "cooling_power_kw": cool, "pue": (it + cool) / it}


# ------------------------------------------------------------------------------------------------ pre-registration
def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def fingerprint(data: CalibrationData) -> str:
    h = hashlib.sha256()
    h.update(data.dataset_id.encode())
    h.update(np.ascontiguousarray(data.ts.astype("int64")).tobytes())
    for ch in INPUT_CHANNELS + OUTPUT_CHANNELS:
        h.update(np.nan_to_num(data.values[ch], nan=-9.99e9).tobytes())
        h.update(data.observed[ch].tobytes())
    h.update("|".join(map(str, data.mode)).encode())
    return h.hexdigest()


def _block_bounds(n: int, split: tuple[float, float, float]) -> tuple[int, int]:
    return int(n * split[0]), int(n * (split[0] + split[1]))


def _eligible(
    data: CalibrationData, segs: list[Segment], base: PhysicsParams, min_rows: int, warmup: int
) -> dict[str, Any]:
    rows_ch = {ch: int(sum(np.isfinite(s.obs[ch][warmup:]).sum() for s in segs)) for ch in OUTPUT_CHANNELS}
    mode_rows: dict[str, int] = {}
    for s in segs:
        for k in range(warmup, len(s.util)):
            m = v2.resolve_mode(s.mode[k], float(s.temp[k]), base)
            mode_rows[m] = mode_rows.get(m, 0) + 1
    fit_channels = [ch for ch in OUTPUT_CHANNELS if rows_ch[ch] >= min_rows]
    eligible, skipped = [], {}
    for name, (_, _, modes) in SPECS.items():
        if not fit_channels:
            skipped[name] = "no output channel has enough observed rows"
        elif modes is not None and sum(mode_rows.get(m, 0) for m in modes) < min_rows:
            skipped[name] = f"fewer than {min_rows} rows in mode(s) {list(modes)}"
        else:
            eligible.append(name)
    return {
        "fit_channels": fit_channels,
        "eligible": eligible,
        "skipped": skipped,
        "rows_per_channel": rows_ch,
        "rows_per_mode": mode_rows,
    }


def make_preregistration(
    data: CalibrationData,
    *,
    split: tuple[float, float, float] = (0.6, 0.2, 0.2),
    ridge_grid: tuple[float, ...] = (0.0, 0.001, 0.01),
    min_rows_per_parameter: int = 288,
    warmup_s: float = 3600.0,
    min_segment_steps: int = 24,
    base: PhysicsParams = DEFAULT_PHYSICS_PARAMS,
) -> dict[str, Any]:
    """Everything decided BEFORE any fit. Looks at which channels/modes exist, never at residuals."""
    if abs(sum(split) - 1.0) > 1e-9 or min(split) <= 0:
        raise CalibrationError("split must be three positive fractions summing to 1")
    i_fit, i_val = _block_bounds(data.n_rows, split)
    warm = max(1, math.ceil(warmup_s / data.cadence_s))
    fit_segs = _segments(data, 0, i_fit, min_segment_steps)
    test_segs = _segments(data, i_val, data.n_rows, min_segment_steps)
    el = _eligible(data, fit_segs, base, min_rows_per_parameter, warm)
    test_rows = {
        ch: int(sum(np.isfinite(s.obs[ch][warm:]).sum() for s in test_segs)) for ch in (*OUTPUT_CHANNELS, "pue")
    }
    metrics = [m for m in METRICS_ALL if test_rows[m] >= min_rows_per_parameter]
    body = {
        "schema": SCHEMA,
        "dataset_id": data.dataset_id,
        "synthetic": data.synthetic,
        "data_fingerprint": fingerprint(data),
        "cadence_s": data.cadence_s,
        "split": list(split),
        "split_rows": [i_fit, i_val, data.n_rows],
        "ridge_grid": list(ridge_grid),
        "min_rows_per_parameter": min_rows_per_parameter,
        "warmup_steps": warm,
        "min_segment_steps": min_segment_steps,
        "base_params_hash": base.params_hash(),
        "fit_channels": el["fit_channels"],
        "candidate_parameters": el["eligible"],
        "not_eligible": el["skipped"],
        "metrics": metrics,
        "acceptance": "fitted model RMSE < published-parameter RMSE AND < one-step persistence RMSE on EVERY metric; otherwise 'no improvement'",
        "one_step_persistence_note": "persistence uses the observed previous step; the model runs free over each day. This favours persistence.",
    }
    body["split_id"] = _sha([body["data_fingerprint"], body["split_rows"]])[:12]
    return {**body, "sha256": _sha(body)}


def _verify(prereg: dict[str, Any], data: CalibrationData) -> None:
    body = {k: v for k, v in prereg.items() if k != "sha256"}
    if _sha(body) != prereg.get("sha256"):
        raise CalibrationError("pre-registration hash does not match its content")
    if body["data_fingerprint"] != fingerprint(data):
        raise CalibrationError("dataset differs from the one the pre-registration was written for")
    if not body["metrics"] or not body["candidate_parameters"]:
        raise CalibrationError("nothing to fit or nothing to score: the data does not cover the required channels")


# ------------------------------------------------------------------------------------------------ optimiser
def _to_params(base: PhysicsParams, names: list[str], u: np.ndarray) -> PhysicsParams:
    vals = {}
    for n, ui in zip(names, u):
        lo, hi, _ = SPECS[n]
        vals[n] = float(math.exp(math.log(lo) + float(np.clip(ui, 0.0, 1.0)) * (math.log(hi) - math.log(lo))))
    return replace(base, **vals)


def _to_u(base: PhysicsParams, names: list[str]) -> np.ndarray:
    out = []
    for n in names:
        lo, hi, _ = SPECS[n]
        out.append((math.log(getattr(base, n)) - math.log(lo)) / (math.log(hi) - math.log(lo)))
    return np.clip(np.array(out), 0.0, 1.0)


class _Problem:
    def __init__(
        self,
        segs: list[Segment],
        base: PhysicsParams,
        names: list[str],
        channels: list[str],
        dt: float,
        warm: int,
        scales: dict[str, float],
    ):
        self.segs, self.base, self.names, self.channels, self.dt, self.warm, self.scales = (
            segs,
            base,
            names,
            channels,
            dt,
            warm,
            scales,
        )
        self.n_res = sum(int(np.isfinite(s.obs[c][warm:]).sum()) for s in segs for c in channels)

    def residual(self, u: np.ndarray) -> np.ndarray:
        try:
            params = _to_params(self.base, self.names, u)
            v2.check_step_stability(params, self.dt)
        except (PhysicsParamsError, v2.PhysicsStabilityError):
            return np.full(self.n_res, PENALTY)
        parts = []
        for s in self.segs:
            pred = simulate(params, s, self.dt)
            for c in self.channels:
                o, p = s.obs[c][self.warm :], pred[c][self.warm :]
                m = np.isfinite(o)
                parts.append((p[m] - o[m]) / self.scales[c])
        return np.concatenate(parts) if parts else np.zeros(0)

    def jacobian(self, u: np.ndarray, r0: np.ndarray, h: float = 1e-3) -> np.ndarray:
        J = np.empty((len(r0), len(u)))
        for j in range(len(u)):
            step = h if u[j] + h <= 1.0 else -h
            u2 = u.copy()
            u2[j] += step
            J[:, j] = (self.residual(u2) - r0) / step
        return J


def _lm(problem: _Problem, u0: np.ndarray, prior: np.ndarray, ridge: float, max_iter: int) -> tuple[np.ndarray, float]:
    w = math.sqrt(ridge * max(problem.n_res, 1))

    def aug(u: np.ndarray) -> np.ndarray:
        r = problem.residual(u)
        return np.concatenate([r, w * (u - prior)]) if ridge > 0 else r

    u = np.clip(u0.copy(), 0.0, 1.0)
    r = aug(u)
    cost = float(r @ r)
    mu = 1e-2
    for _ in range(max_iter):
        J = problem.jacobian(u, r[: problem.n_res])
        if ridge > 0:
            J = np.vstack([J, w * np.eye(len(u))])
        A, g = J.T @ J, J.T @ r
        improved = False
        for _try in range(8):
            delta = np.linalg.solve(A + mu * np.diag(np.diag(A) + 1e-12), -g)
            u_new = np.clip(u + delta, 0.0, 1.0)
            r_new = aug(u_new)
            c_new = float(r_new @ r_new)
            if c_new < cost:
                done = (cost - c_new) <= 1e-9 * max(cost, 1e-12)
                u, r, cost, mu, improved = u_new, r_new, c_new, max(mu / 3.0, 1e-9), True
                if done:
                    return u, cost
                break
            mu *= 4.0
        if not improved:
            break
    return u, cost


def _identifiability(problem: _Problem, u: np.ndarray) -> dict[str, Any]:
    r0 = problem.residual(u)
    J = problem.jacobian(u, r0)
    sens = np.linalg.norm(J, axis=0)
    rel = sens / max(float(sens.max()), 1e-300)
    cov = np.linalg.pinv(J.T @ J)
    d = np.sqrt(np.clip(np.diag(cov), 1e-300, None))
    corr = cov / np.outer(d, d)
    reasons: dict[str, str] = {}
    for j, n in enumerate(problem.names):
        if rel[j] < 1e-2:
            reasons[n] = f"insensitive (relative sensitivity {rel[j]:.1e})"
        elif u[j] < 1e-3 or u[j] > 1 - 1e-3:
            reasons[n] = "estimate sits on its physical bound"
    for j in range(len(u)):
        for k in range(j + 1, len(u)):
            if abs(corr[j, k]) > 0.98:
                weaker = j if rel[j] < rel[k] else k
                other = k if weaker == j else j
                reasons.setdefault(
                    problem.names[weaker], f"collinear with {problem.names[other]} (|corr| {abs(corr[j, k]):.3f})"
                )
    sv = np.linalg.svd(J / np.maximum(sens, 1e-300), compute_uv=False)
    return {
        "relative_sensitivity": {n: float(rel[i]) for i, n in enumerate(problem.names)},
        "max_abs_correlation": float(np.max(np.abs(corr - np.eye(len(u))))) if len(u) > 1 else 0.0,
        "condition_number": float(sv[0] / max(sv[-1], 1e-300)),
        "not_identified": reasons,
    }


# ------------------------------------------------------------------------------------------------ scoring
class _OneShotTest:
    def __init__(self, segs: list[Segment], dt: float, warm: int, metrics: list[str]):
        self._segs, self._dt, self._warm, self._metrics, self._used = segs, dt, warm, metrics, False

    def score(self, models: dict[str, PhysicsParams]) -> dict[str, dict[str, dict[str, float]]]:
        if self._used:
            raise TestBlockAlreadyScored("the test block has been scored; it cannot be scored again")
        self._used = True
        err: dict[str, dict[str, list[np.ndarray]]] = {
            m: {k: [] for k in self._metrics} for m in (*models, "persistence")
        }
        for s in self._segs:
            preds = {name: simulate(p, s, self._dt) for name, p in models.items()}
            for k in self._metrics:
                o = s.obs[k]
                valid = np.isfinite(o)
                valid[: self._warm] = False
                valid[1:] &= np.isfinite(o[:-1])
                valid[0] = False
                for name in models:
                    valid &= np.isfinite(preds[name][k])
                if not valid.any():
                    continue
                for name in models:
                    err[name][k].append(preds[name][k][valid] - o[valid])
                prev = np.concatenate([[np.nan], o[:-1]])
                err["persistence"][k].append(prev[valid] - o[valid])
        out: dict[str, dict[str, dict[str, float]]] = {}
        for name, per in err.items():
            out[name] = {}
            for k, parts in per.items():
                e = np.concatenate(parts) if parts else np.zeros(0)
                out[name][k] = {"rmse": float(np.sqrt(np.mean(e**2))) if len(e) else float("nan"), "n": int(len(e))}
        return out


def _val_cost(problem: _Problem, u: np.ndarray) -> float:
    r = problem.residual(u)
    return float(r @ r) / max(len(r), 1)


# ------------------------------------------------------------------------------------------------ driver
def calibrate(
    data: CalibrationData,
    prereg: dict[str, Any],
    *,
    base: PhysicsParams = DEFAULT_PHYSICS_PARAMS,
    n_boot: int = 0,
    seed: int = 0,
    max_iter: int = 40,
) -> dict[str, Any]:
    _verify(prereg, data)
    if base.params_hash() != prereg["base_params_hash"]:
        raise CalibrationError("base parameters differ from the pre-registered ones")
    dt, warm = data.cadence_s, int(prereg["warmup_steps"])
    i_fit, i_val, n = prereg["split_rows"]
    msteps = int(prereg["min_segment_steps"])
    fit_segs = _segments(data, 0, i_fit, msteps)
    val_segs = _segments(data, i_fit, i_val, msteps)
    test_segs = _segments(data, i_val, n, msteps)
    names, channels = list(prereg["candidate_parameters"]), list(prereg["fit_channels"])
    if not fit_segs or not val_segs or not test_segs:
        raise CalibrationError("a block has no contiguous usable run; need more or cleaner data")

    scales = {}
    for c in channels:
        vals = np.concatenate([s.obs[c][warm:] for s in fit_segs])
        vals = vals[np.isfinite(vals)]
        scales[c] = float(max(np.std(vals), 0.01 * abs(np.mean(vals)), 1e-6))

    prior = _to_u(base, names)
    pf = _Problem(fit_segs, base, names, channels, dt, warm, scales)
    pv = _Problem(val_segs, base, names, channels, dt, warm, scales)

    # 2. the one model option, chosen on the validation block only
    trials = []
    for ridge in prereg["ridge_grid"]:
        u_r, _ = _lm(pf, prior, prior, ridge, max_iter)
        trials.append((_val_cost(pv, u_r), ridge, u_r))
    val_cost, ridge, u_hat = min(trials, key=lambda t: t[0])

    # 3. identifiability, then refit the identified subset
    ident = _identifiability(pf, u_hat)
    keep = [i for i, nme in enumerate(names) if nme not in ident["not_identified"]]
    kept = [names[i] for i in keep]
    if kept and len(kept) < len(names):
        pk = _Problem(fit_segs, base, kept, channels, dt, warm, scales)
        u_k, _ = _lm(pk, _to_u(base, kept), _to_u(base, kept), ridge, max_iter)
    elif kept:
        pk, u_k = pf, u_hat
    else:
        pk, u_k = None, np.zeros(0)
    fitted = _to_params(base, kept, u_k) if kept else base

    # 4. one-shot test scoring: fitted, published, persistence
    scores = _OneShotTest(test_segs, dt, warm, list(prereg["metrics"])).score({"fitted": fitted, "published": base})

    # 5. verdict against both nulls on every pre-registered metric
    failures = []
    for k in prereg["metrics"]:
        f, p, q = scores["fitted"][k]["rmse"], scores["published"][k]["rmse"], scores["persistence"][k]["rmse"]
        if not (f < p and f < q):
            failures.append({"metric": k, "fitted": f, "published": p, "persistence": q})
    improved = bool(kept) and not failures

    # 6. optional block bootstrap over days
    intervals: dict[str, list[float]] = {}
    if n_boot > 0 and kept:
        rng = np.random.default_rng(seed)
        by_day: dict[int, list[Segment]] = {}
        for s in fit_segs:
            by_day.setdefault(s.day, []).append(s)
        days = sorted(by_day)
        draws = []
        for _ in range(n_boot):
            pick = rng.choice(len(days), size=len(days), replace=True)
            segs_b = [s for d in pick for s in by_day[days[int(d)]]]
            pb = _Problem(segs_b, base, kept, channels, dt, warm, scales)
            u_b, _ = _lm(pb, u_k, _to_u(base, kept), ridge, 12)
            draws.append([getattr(_to_params(base, kept, u_b), nme) for nme in kept])
        arr = np.array(draws)
        intervals = {
            nme: [float(np.percentile(arr[:, i], 5)), float(np.percentile(arr[:, i], 95))] for i, nme in enumerate(kept)
        }

    if data.synthetic:
        label = "synthetic parameter-recovery test; not a calibration"
    elif improved:
        label = f"calibrated to dataset {data.dataset_id}, {data.n_days:.1f} days, split {prereg['split_id']}"
    else:
        label = "uncalibrated: no improvement over the nulls on the pre-registered test block"

    table = {}
    for nme in names:
        if nme in kept:
            table[nme] = {
                "status": "fitted",
                "published": getattr(base, nme),
                "fitted": getattr(fitted, nme),
                "interval_5_95": intervals.get(nme),
            }
        else:
            table[nme] = {
                "status": "not identified",
                "reason": ident["not_identified"].get(nme, "dropped"),
                "published": getattr(base, nme),
            }
    for nme, why in prereg["not_eligible"].items():
        table[nme] = {"status": "not eligible", "reason": why, "published": getattr(base, nme)}

    return {
        "schema": SCHEMA,
        "label": label,
        "verdict": "improved" if improved else "no_improvement",
        "synthetic": data.synthetic,
        "dataset_id": data.dataset_id,
        "preregistration_sha256": prereg["sha256"],
        "split_id": prereg["split_id"],
        "ridge_chosen_on_validation": ridge,
        "validation_mse": val_cost,
        "fit_rows_used": pf.n_res,
        "parameters": table,
        "identifiability": ident,
        "test_scores": scores,
        "failures": failures,
        "published_params_hash": base.params_hash(),
        "fitted_params_hash": fitted.params_hash(),
        "fitted_params": fitted.as_dict(),
        "all_other_parameters": "unchanged from the published values",
        "scope": "this facility and period only; not a claim about any other facility",
    }
