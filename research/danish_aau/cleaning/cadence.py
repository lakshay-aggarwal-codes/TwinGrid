"""Cadence profile of one file's stored timestamps (steps between consecutive DISTINCT naive timestamps).

Aggregates only. It reports where a step is large (timestamp texts at both ends) but never fills, resamples or
interprets a gap. Steps are in naive label seconds (timezone not established, so they equal elapsed time only if the
source clock never jumped).
"""

from __future__ import annotations

from collections import Counter

import numpy as np


def cadence_profile(
    ts_ns: np.ndarray, ts_text: np.ndarray, nominal_s: float | None, *, big_factor: float = 2.0, keep: int = 20
) -> dict:
    ts_ns = np.asarray(ts_ns, dtype=np.int64)
    if ts_ns.size == 0:
        return {"distinct_timestamps": 0}
    change = np.concatenate(([True], np.diff(ts_ns) != 0))
    u_ns, u_txt = ts_ns[change], np.asarray(ts_text, dtype=object)[change]
    steps = np.diff(u_ns) / 1e9
    out: dict = {
        "distinct_timestamps": int(u_ns.size),
        "backward_steps": int((steps < 0).sum()),
        "nominal_interval_s": nominal_s,
    }
    if steps.size == 0:
        return out
    hist = Counter(int(round(s)) if float(s).is_integer() else float(s) for s in steps.tolist())
    out["step_histogram_top"] = {str(k): v for k, v in hist.most_common(15)}
    out["distinct_step_values"] = len(hist)
    out["min_step_s"] = float(steps.min())
    j = int(np.argmax(steps))
    out["max_step_s"] = float(steps[j])
    out["max_step_between"] = [str(u_txt[j]), str(u_txt[j + 1])]
    if nominal_s:
        thr = big_factor * nominal_s
        big = np.flatnonzero(steps > thr)
        out["big_step_threshold_s"] = thr
        out["steps_above_threshold"] = int(big.size)
        out["largest_steps"] = [
            {"after": str(u_txt[i]), "before": str(u_txt[i + 1]), "step_s": float(steps[i])}
            for i in big[np.argsort(-steps[big], kind="stable")][:keep]
        ]
    return out
