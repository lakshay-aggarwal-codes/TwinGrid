"""Leakage-safe dataset plumbing (T25, roadmap section 13.3).

Pure functions, no simulation and no models:

* ``load_split_config`` / ``load_scenario_config``: validated JSON configs with content-derived ids.
* ``build_scenarios``: the exact scenario list (cell x regime x seed) implied by the two configs.
* ``validate_split``: disjoint city x month-block cells, disjoint seed ranges, and a test partition that holds
  >= 1 city, >= 1 month-block and >= 1 workload regime absent from train and val.
* ``fit_preprocessing`` / ``verify_preprocessing``: scalers and clip bounds are fit on TRAIN rows only and record
  ``fit_split_id``; the verifier recomputes them from the train rows and compares.
* ``assert_events_within_scenarios``: no anomaly event crosses a scenario (hence split) boundary.
* ``canonical_json`` / ``sha256_*`` / ``dataset_id``: a dataset id is the SHA-256 of its canonical manifest.
* cleaned-input registry (``data/cleaned/MANIFEST.json``): sha256 of every cleaned input the generator may read.

Nothing here reads the global NumPy RNG.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLITS_DIR = REPO_ROOT / "configs" / "splits"
SCENARIOS_DIR = REPO_ROOT / "configs" / "scenarios"
CLEANED_DIR = REPO_ROOT / "data" / "cleaned"
CLEANED_MANIFEST_PATH = CLEANED_DIR / "MANIFEST.json"
DEFAULT_SPLIT_PATH = SPLITS_DIR / "split_v2.json"
DEFAULT_SCENARIO_PATH = SCENARIOS_DIR / "scenario_set_v2.json"

SPLITS = ("train", "val", "test")
HELD_OUT_REGIMES = ("burst",)  # documentation only: the config decides what is held out
KNOWN_REGIMES = ("low", "diurnal", "high", "burst")

# Feature columns the preprocessing statistics are fit on (a fixed, ordered list: part of the manifest).
FEATURE_COLUMNS: tuple[str, ...] = (
    "server_utilisation",
    "outside_temp_C",
    "server_inlet_temp_C",
    "server_outlet_temp_C",
    "it_power_kw",
    "cooling_power_kw",
    "total_power_kw",
    "pue",
    "water_flow_lpm",
    "water_consumed_L",
    "wue",
    "humidity_pct",
    "water_pressure_bar",
    "water_stress",
)
CLIP_QUANTILES = (0.005, 0.995)


class DatasetConfigError(ValueError):
    """A split/scenario config or a dataset violates the leakage rules."""


class MissingInputError(FileNotFoundError):
    """A required cleaned input is missing. Never worked around silently (see ``--allow-synthetic-weather``)."""


# ----------------------------------------------------------------------------- hashing and canonical JSON
def canonical_json(obj: Any) -> str:
    """Sorted keys, no whitespace, ASCII only, no NaN: the same object always gives the same bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def dataset_id(manifest: Mapping[str, Any]) -> str:
    """Dataset id = SHA-256 of the canonical manifest (``dataset_id`` itself excluded)."""
    body = {k: v for k, v in manifest.items() if k != "dataset_id"}
    return sha256_text(canonical_json(body))


# ----------------------------------------------------------------------------- configs
def _load_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def config_id(config: Mapping[str, Any]) -> str:
    """Content id of a config: SHA-256 of its canonical JSON."""
    return sha256_text(canonical_json({k: v for k, v in config.items() if k != "split_id"}))


def load_split_config(path: Path = DEFAULT_SPLIT_PATH) -> dict[str, Any]:
    cfg = _load_json(path)
    validate_split(cfg)
    cfg["split_id"] = config_id(cfg)
    return cfg


def load_scenario_config(path: Path = DEFAULT_SCENARIO_PATH) -> dict[str, Any]:
    cfg = _load_json(path)
    validate_scenario_config(cfg)
    cfg["scenario_set_id"] = config_id(cfg)
    return cfg


def _cell_keys(cells: Iterable[Mapping[str, str]]) -> list[tuple[str, str]]:
    return [(c["city"], c["month_block"]) for c in cells]


def validate_split(cfg: Mapping[str, Any]) -> None:
    """Raise DatasetConfigError unless the split satisfies section 13.3."""
    for key in ("year", "month_blocks", "cells", "scenario_seed_ranges", "workload_regimes"):
        if key not in cfg:
            raise DatasetConfigError(f"split config lacks {key!r}")
    blocks = set(cfg["month_blocks"])
    cells = {s: _cell_keys(cfg["cells"].get(s, [])) for s in SPLITS}
    for s in SPLITS:
        if not cells[s]:
            raise DatasetConfigError(f"split {s!r} has no cells")
        if len(cells[s]) != len(set(cells[s])):
            raise DatasetConfigError(f"split {s!r} lists a cell twice")
        unknown = {b for _, b in cells[s]} - blocks
        if unknown:
            raise DatasetConfigError(f"split {s!r} uses undefined month blocks {sorted(unknown)}")
    months = [m for ms in cfg["month_blocks"].values() for m in ms]
    if sorted(months) != sorted(set(months)) or not set(months) <= set(range(1, 13)):
        raise DatasetConfigError("month_blocks must be disjoint sets of months 1..12")

    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        shared = set(cells[a]) & set(cells[b])
        if shared:
            raise DatasetConfigError(f"cells shared by {a} and {b}: {sorted(shared)[:5]}")

    ranges = cfg["scenario_seed_ranges"]
    spans = []
    for s in SPLITS:
        lo, hi = ranges[s]
        if not (isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi):
            raise DatasetConfigError(f"bad seed range for {s}: {ranges[s]}")
        spans.append((lo, hi, s))
    spans.sort()
    for (_, hi_a, a), (lo_b, _, b) in zip(spans, spans[1:], strict=False):
        if lo_b <= hi_a:
            raise DatasetConfigError(f"seed ranges of {a} and {b} overlap")
    if [s for *_, s in spans] != list(SPLITS):
        raise DatasetConfigError("seed ranges must be ordered train < val < test")

    seen_cities = {c for s in ("train", "val") for c, _ in cells[s]}
    seen_blocks = {b for s in ("train", "val") for _, b in cells[s]}
    seen_regimes = set(cfg["workload_regimes"]["train"]) | set(cfg["workload_regimes"]["val"])
    if not {c for c, _ in cells["test"]} - seen_cities:
        raise DatasetConfigError("test must hold at least one city absent from train and val")
    if not {b for _, b in cells["test"]} - seen_blocks:
        raise DatasetConfigError("test must hold at least one month-block absent from train and val")
    if not set(cfg["workload_regimes"]["test"]) - seen_regimes:
        raise DatasetConfigError("test must hold at least one workload regime absent from train and val")
    for s in SPLITS:
        bad = set(cfg["workload_regimes"][s]) - set(KNOWN_REGIMES)
        if bad:
            raise DatasetConfigError(f"unknown workload regimes in {s}: {sorted(bad)}")


def validate_scenario_config(cfg: Mapping[str, Any]) -> None:
    for key in ("interval_minutes", "days_per_scenario", "scenarios_per_cell", "facility", "injection"):
        if key not in cfg:
            raise DatasetConfigError(f"scenario config lacks {key!r}")
    if cfg["interval_minutes"] <= 0 or cfg["days_per_scenario"] <= 0:
        raise DatasetConfigError("interval_minutes and days_per_scenario must be positive")
    for s in SPLITS:
        if int(cfg["scenarios_per_cell"].get(s, 0)) < 1:
            raise DatasetConfigError(f"scenarios_per_cell[{s!r}] must be >= 1")
    inj = cfg["injection"]
    for etype, spec in inj["per_scenario"].items():
        if int(spec["count"]) < 0:
            raise DatasetConfigError(f"injection count for {etype} must be >= 0")


def events_per_scenario(scenario_cfg: Mapping[str, Any]) -> int:
    return sum(int(spec["count"]) for spec in scenario_cfg["injection"]["per_scenario"].values())


# ----------------------------------------------------------------------------- scenarios
@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    split: str
    city: str
    month_block: str
    regime: str
    seed: int
    days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "split": self.split,
            "city": self.city,
            "month_block": self.month_block,
            "regime": self.regime,
            "seed": self.seed,
            "days": self.days,
        }


def build_scenarios(split_cfg: Mapping[str, Any], scenario_cfg: Mapping[str, Any]) -> list[Scenario]:
    """Every scenario of every split, in a fixed order. Seeds run consecutively from the start of the split's
    range over the cells sorted by (city, block); regimes cycle through the split's regime list."""
    out: list[Scenario] = []
    per_cell = scenario_cfg["scenarios_per_cell"]
    for split in SPLITS:
        lo, hi = split_cfg["scenario_seed_ranges"][split]
        regimes = list(split_cfg["workload_regimes"][split])
        seed = lo
        for city, block in sorted(_cell_keys(split_cfg["cells"][split])):
            for k in range(int(per_cell[split])):
                if seed > hi:
                    raise DatasetConfigError(f"seed range of {split} exhausted at {city}/{block}")
                out.append(
                    Scenario(
                        scenario_id=f"{split}-{seed}",
                        split=split,
                        city=city,
                        month_block=block,
                        regime=regimes[(seed - lo) % len(regimes)],
                        seed=seed,
                        days=int(scenario_cfg["days_per_scenario"]),
                    )
                )
                seed += 1
    ids = [s.scenario_id for s in out]
    if len(ids) != len(set(ids)):
        raise DatasetConfigError("duplicate scenario ids")
    return out


def planned_event_counts(split_cfg: Mapping[str, Any], scenario_cfg: Mapping[str, Any]) -> dict[str, int]:
    """Events per split implied by the configs alone (no data needed)."""
    scenarios = build_scenarios(split_cfg, scenario_cfg)
    per = events_per_scenario(scenario_cfg)
    return {s: sum(1 for sc in scenarios if sc.split == s) * per for s in SPLITS}


def assert_membership_disjoint(rows: pd.DataFrame) -> None:
    """``rows`` needs columns scenario_id, split, city, month_block. Raise if any scenario or cell sits in 2 splits."""
    per_scenario = rows.groupby("scenario_id")["split"].nunique()
    if (per_scenario > 1).any():
        raise DatasetConfigError(f"scenarios in more than one split: {list(per_scenario[per_scenario > 1].index)[:5]}")
    cells = rows.drop_duplicates(["city", "month_block", "split"])
    per_cell = cells.groupby(["city", "month_block"])["split"].nunique()
    if (per_cell > 1).any():
        raise DatasetConfigError(f"cells in more than one split: {list(per_cell[per_cell > 1].index)[:5]}")


# ----------------------------------------------------------------------------- events
EVENT_COLUMNS = ("event_id", "scenario_id", "split", "type", "start", "end", "start_idx", "end_idx", "params")


def assert_events_within_scenarios(events: pd.DataFrame, scenario_rows: Mapping[str, tuple[int, int]]) -> None:
    """Every event [start_idx, end_idx) must lie inside its own scenario's rows ``[0, n_rows)``.

    ``scenario_rows`` maps scenario_id -> (0, n_rows). Scenarios are separate series, so an event inside its
    scenario cannot cross a split boundary."""
    for row in events.itertuples(index=False):
        if row.scenario_id not in scenario_rows:
            raise DatasetConfigError(f"event {row.event_id} refers to unknown scenario {row.scenario_id}")
        lo, hi = scenario_rows[row.scenario_id]
        if not (lo <= row.start_idx < row.end_idx <= hi):
            raise DatasetConfigError(
                f"event {row.event_id} [{row.start_idx}, {row.end_idx}) leaves its scenario rows [{lo}, {hi})"
            )
    split_of = events.groupby("scenario_id")["split"].nunique()
    if (split_of > 1).any():
        raise DatasetConfigError("an event table maps one scenario to several splits")


# ----------------------------------------------------------------------------- train-only preprocessing
def fit_preprocessing(
    train_rows: pd.DataFrame,
    *,
    fit_split_id: str,
    columns: Sequence[str] = FEATURE_COLUMNS,
) -> dict[str, Any]:
    """Statistics fit on ``train_rows`` ONLY: min/max/mean/std (a scaler) and 0.5 %/99.5 % clip bounds (a threshold
    table). ``fit_split_id`` names the split the rows came from and is stored with the result."""
    if not isinstance(fit_split_id, str) or not fit_split_id:
        raise DatasetConfigError("fit_split_id is required")
    if "split" in train_rows.columns and set(train_rows["split"].unique()) - {"train"}:
        raise DatasetConfigError("fit_preprocessing was given non-train rows")
    values = train_rows[list(columns)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise DatasetConfigError("non-finite values in the training rows")
    lo_q, hi_q = CLIP_QUANTILES
    return {
        "fit_split_id": fit_split_id,
        "fit_rows": int(len(train_rows)),
        "columns": list(columns),
        "min": [float(v) for v in values.min(axis=0)],
        "max": [float(v) for v in values.max(axis=0)],
        "mean": [float(v) for v in values.mean(axis=0)],
        "std": [float(v) for v in values.std(axis=0)],
        "clip_quantiles": [lo_q, hi_q],
        "clip_low": [float(v) for v in np.quantile(values, lo_q, axis=0)],
        "clip_high": [float(v) for v in np.quantile(values, hi_q, axis=0)],
    }


def verify_preprocessing(
    stored: Mapping[str, Any], train_rows: pd.DataFrame, *, expected_fit_split_id: str, rtol: float = 1e-9
) -> None:
    """Recompute the statistics from ``train_rows`` and require them to equal ``stored``."""
    if stored.get("fit_split_id") != expected_fit_split_id:
        raise DatasetConfigError(
            f"preprocessing was fit on {stored.get('fit_split_id')!r}, expected {expected_fit_split_id!r}"
        )
    fresh = fit_preprocessing(train_rows, fit_split_id=expected_fit_split_id, columns=stored["columns"])
    for key in ("fit_rows", "columns", "clip_quantiles"):
        if fresh[key] != stored[key]:
            raise DatasetConfigError(f"stored preprocessing {key} differs from the training rows")
    for key in ("min", "max", "mean", "std", "clip_low", "clip_high"):
        if not np.allclose(fresh[key], stored[key], rtol=rtol, atol=1e-12):
            raise DatasetConfigError(f"stored preprocessing {key} does not match the training rows")


# ----------------------------------------------------------------------------- cleaned-input registry
def cleaned_input_entry(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise MissingInputError(f"required cleaned input is missing: {path}")
    with path.open("rb") as fh:
        n_rows = max(0, sum(1 for _ in fh) - 1)
    try:
        shown = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:  # outside the repository (e.g. a temp directory): keep the absolute path
        shown = path.resolve().as_posix()
    return {"path": shown, "sha256": sha256_file(path), "rows": n_rows}


def register_cleaned_inputs(paths: Iterable[Path], manifest_path: Path = CLEANED_MANIFEST_PATH) -> dict[str, Any]:
    """Write data/cleaned/MANIFEST.json from the files as they are NOW. An explicit owner action: the generator
    only ever verifies against this registry, it never creates it."""
    entries = sorted((cleaned_input_entry(p) for p in paths), key=lambda e: e["path"])
    manifest = {"schema": 1, "inputs": entries}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def verify_cleaned_inputs(paths: Iterable[Path], manifest_path: Path = CLEANED_MANIFEST_PATH) -> list[dict[str, Any]]:
    """Return the manifest entries for ``paths`` after checking each file's sha256 against the registry."""
    if not Path(manifest_path).is_file():
        raise MissingInputError(
            f"{manifest_path} does not exist: register the cleaned inputs first (make_datasets.py --register-inputs)"
        )
    registry = {e["path"]: e for e in _load_json(manifest_path)["inputs"]}
    verified = []
    for path in paths:
        current = cleaned_input_entry(path)
        recorded = registry.get(current["path"])
        if recorded is None:
            raise DatasetConfigError(f"{current['path']} is not listed in {manifest_path}")
        if recorded["sha256"] != current["sha256"]:
            raise DatasetConfigError(
                f"{current['path']} changed since it was registered "
                f"(sha256 {current['sha256']} != {recorded['sha256']})"
            )
        verified.append(current)
    return verified
