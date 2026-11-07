"""Parse Task 14 panel TSV chunks into integer arrays. Build/verify side only (needs numpy and pandas)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .errors import BundleError
from .schema import QUALITY_FLAGGED, QUALITY_OK, STATE_MISSING, STATE_OBSERVED

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
OBS_HEADER = [
    "ts_text",
    "value_ticks",
    "state",
    "quality",
    "reason_code",
    "disposition",
    "group_size",
    "first_row_ordinal",
]
DERIVED_HEADER = ["ts_text", "value_ticks", "state", "quality", "reason_code"]
_STATE = {"observed": STATE_OBSERVED, "missing": STATE_MISSING}
_QUALITY = {"ok": QUALITY_OK, "flagged": QUALITY_FLAGGED}
_DISPOSITION = {"retained": 1, "conflict_cell_missing": 2}
MEASURED_REASONS = {"conflict_unresolved_tie": 1, "blank_cell": 2}
DERIVED_REASONS = {"inputs_not_all_observed": 3}


@dataclass
class Chunk:
    ts_text: np.ndarray  # object (n,)
    t: np.ndarray  # int64 label-seconds
    ticks: np.ndarray  # int64, 0 where null
    ticks_null: np.ndarray  # int8
    state: np.ndarray  # int8
    quality: np.ndarray  # int8, -1 null
    reason: np.ndarray  # int8, 0 null
    disposition: np.ndarray | None  # int8 (measured only)
    group_size: np.ndarray | None  # int32
    first_row: np.ndarray | None  # int64


def check_header(path: Path, header: list[str]) -> None:
    with open(path, encoding="utf-8", newline="") as f:
        first = f.readline()
    if first.rstrip("\n").split("\t") != header:
        raise BundleError(f"{path.name}: unexpected TSV header")


def timestamps_to_seconds(texts: np.ndarray) -> np.ndarray:
    """Naive label-seconds (``calendar.timegm`` semantics: no zone, no DST). Strict: every text must round-trip."""
    s = pd.Series(texts, dtype=object)
    ok = s.str.fullmatch(TS_RE.pattern)
    if not bool(ok.all()):
        raise BundleError(f"timestamp text not in 'YYYY-MM-DD HH:MM:SS' form, e.g. {s[~ok].iloc[0]!r}")
    try:
        dt = np.array([x.replace(" ", "T") for x in texts], dtype="datetime64[s]")
    except ValueError as exc:
        raise BundleError(f"unparseable timestamp text: {exc}") from None
    back = np.datetime_as_string(dt, unit="s")
    if not np.array_equal(np.char.replace(back, "T", " "), texts.astype("U19")):
        raise BundleError("timestamp text does not round-trip (invalid date)")
    return dt.astype("int64")


def iter_chunks(path: Path, *, derived: bool, chunk_rows: int) -> Iterator[Chunk]:
    path = Path(path)
    header = DERIVED_HEADER if derived else OBS_HEADER
    check_header(path, header)
    reasons = DERIVED_REASONS if derived else MEASURED_REASONS
    for df in pd.read_csv(
        path, sep="\t", dtype=str, keep_default_na=False, na_values=[], chunksize=chunk_rows, encoding="utf-8"
    ):
        ts = df["ts_text"].to_numpy(dtype=object)
        state = df["state"].map(_STATE)
        quality = df["quality"].map({**_QUALITY, "": -1})
        reason = df["reason_code"].map({**reasons, "": 0})
        vt = df["value_ticks"]
        null = (vt == "").to_numpy()
        problems: list[str] = []
        if state.isna().any():
            problems.append("state outside {observed, missing}")
        if quality.isna().any():
            problems.append("quality outside {ok, flagged, empty}")
        if reason.isna().any():
            problems.append("unknown reason_code")
        if problems:
            raise BundleError(f"{path.name}: invalid rows: " + "; ".join(problems))
        st, qu, re_ = state.to_numpy(np.int8), quality.to_numpy(np.int8), reason.to_numpy(np.int8)
        ticks = np.zeros(len(df), dtype=np.int64)
        if (~null).any():
            try:
                ticks[~null] = vt[~null].astype("int64").to_numpy()
            except ValueError:
                raise BundleError(f"{path.name}: value_ticks is not an integer") from None
        obs = st == STATE_OBSERVED
        if (obs & null).any() or (~obs & ~null).any():
            raise BundleError(f"{path.name}: observed rows need a value and missing rows must have none")
        if (obs & (qu < 0)).any() or (~obs & (qu >= 0)).any():
            raise BundleError(f"{path.name}: quality must be set exactly on observed rows")
        if (obs & (re_ != 0)).any() or (~obs & (re_ == 0)).any():
            raise BundleError(f"{path.name}: reason_code must be set exactly on missing rows")
        if (qu == QUALITY_FLAGGED).any():
            raise BundleError(
                f"{path.name}: flagged cells present; bundle v1 supports only the default cleaning configuration"
            )
        disp = gs = first = None
        if not derived:
            d = df["disposition"].map(_DISPOSITION)
            if d.isna().any():
                raise BundleError(f"{path.name}: disposition outside {sorted(_DISPOSITION)}")
            disp = d.to_numpy(np.int8)
            try:
                gs = df["group_size"].astype("int64").to_numpy().astype(np.int32)
                first = df["first_row_ordinal"].astype("int64").to_numpy()
            except ValueError:
                raise BundleError(f"{path.name}: group_size / first_row_ordinal are not integers") from None
        yield Chunk(ts, timestamps_to_seconds(ts), ticks, null.astype(np.int8), st, qu, re_, disp, gs, first)
