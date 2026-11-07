"""Content digest over cell records, independent of chunk size (fixed-layout records, little endian)."""

from __future__ import annotations

import numpy as np

REC = np.dtype([("pk", "<i4"), ("t", "<i8"), ("v", "<i8"), ("vn", "i1"), ("s", "i1"), ("q", "i1"), ("r", "i1")])


def update(h, pk: int, t: np.ndarray, v: np.ndarray, v_null: np.ndarray, s: np.ndarray, q: np.ndarray, r: np.ndarray):
    """Feed one chunk of one series. ``q`` and ``r`` use -1 / 0 for null (the same convention in loader and verifier)."""
    rec = np.empty(len(t), dtype=REC)
    rec["pk"] = pk
    rec["t"] = t
    rec["v"] = np.where(v_null.astype(bool), 0, v)
    rec["vn"] = v_null
    rec["s"] = s
    rec["q"] = q
    rec["r"] = r
    h.update(rec.tobytes())
