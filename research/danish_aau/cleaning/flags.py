"""Quality flags: range check and flatline run. Both are OFF by default (owner inputs), neither clips, imputes or drops.

``apply_flags`` returns a COPY of the result with ``flag`` filled and the ledger updated: a raw row whose disposition is
``retained`` becomes ``flagged`` when its stored second carries at least one flagged Tier 1 cell. Conflict and
exact-duplicate dispositions are never overwritten.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import numpy as np

from ..protocol.protocol import Protocol
from ..protocol.rules import to_ticks
from .catalogue import D_FLAGGED, D_RETAINED, FLAG_FLATLINE, FLAG_OUT_OF_RANGE
from .config import CleanConfig
from .resolve import CleanResult


def measurand_class(column: str) -> str:
    return "power" if column.startswith("Power ") else "temperature"


def flatline_runs(valid: np.ndarray, ticks: np.ndarray, t_sec: np.ndarray, min_run: int, gap_step: int) -> np.ndarray:
    """Boolean mask (n,) of samples inside a run of >= ``min_run`` equal observed values at consecutive stored seconds."""
    n = valid.shape[0]
    out = np.zeros(n, dtype=bool)
    if n < 2:
        return out
    link = valid[1:] & valid[:-1] & (np.diff(t_sec) <= gap_step) & (ticks[1:] == ticks[:-1])
    pad = np.concatenate(([False], link, [False])).astype(np.int8)
    edge = np.diff(pad)
    starts, ends = np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)  # link indices; run covers samples s..e
    for s, e in zip(starts, ends, strict=True):
        if (e - s) + 1 >= min_run:
            out[s : e + 1] = True
    return out


def flatline_report(result: CleanResult, min_run: int, gap_step: int) -> dict:
    """Aggregates of what the flatline flag WOULD mark (nothing is applied)."""
    per_col, total_cells, total_runs = {}, 0, 0
    for j, col in enumerate(result.columns):
        m = flatline_runs(result.valid[:, j], result.ticks[:, j], result.t_sec, min_run, gap_step)
        cells = int(m.sum())
        runs = int((np.diff(np.concatenate(([0], m.astype(np.int8)))) == 1).sum())
        per_col[col] = {"cells": cells, "runs": runs}
        total_cells += cells
        total_runs += runs
    return {"min_run": min_run, "gap_step": gap_step, "cells": total_cells, "runs": total_runs, "by_column": per_col}


def apply_flags(result: CleanResult, protocol: Protocol, config: CleanConfig | None = None) -> CleanResult:
    cfg = config or CleanConfig()
    flag = np.zeros_like(result.flag)
    gap = cfg.flatline_gap_step
    if gap is None:
        gap = protocol.family()["gap_min_step_seconds"]
    if cfg.flatline_min_run is not None:
        for j in range(len(result.columns)):
            m = flatline_runs(result.valid[:, j], result.ticks[:, j], result.t_sec, cfg.flatline_min_run, gap)
            flag[m, j] = FLAG_FLATLINE
    for j, col in enumerate(result.columns):
        lim = cfg.range_limits.get(measurand_class(col))
        if lim is None:
            continue
        res = Decimal(result.resolutions[col])
        lo, hi = to_ticks(lim[0], res), to_ticks(lim[1], res)
        if lo > hi:
            raise ValueError(f"range limits for {measurand_class(col)} are reversed")
        out = result.valid[:, j] & ((result.ticks[:, j] < lo) | (result.ticks[:, j] > hi))
        flag[out, j] = FLAG_OUT_OF_RANGE  # priority over the flatline flag
    row_disp = result.row_disp.copy()
    sec_flagged = (flag > 0).any(axis=1)
    hit = (row_disp == D_RETAINED) & sec_flagged[result.row_sec]
    row_disp[hit] = D_FLAGGED
    return replace(result, flag=flag, row_disp=row_disp)
