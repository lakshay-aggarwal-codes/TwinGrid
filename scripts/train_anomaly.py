#!/usr/bin/env python3
"""T26: train the anomaly detector on dataset v2 and evaluate it at event level (roadmap 13.4).

    python scripts/train_anomaly.py --dataset-dir data/datasets/<dataset_id> --config configs/anomaly/anomaly_v2.json

Replaces the anomaly step of notebooks/train_all.py. Protocol, in this order:
  1. verify the dataset (dataset_id == directory name, every file sha256 == manifest; synthetic inputs refused
     unless --allow-synthetic-inputs, which is then recorded)
  2. train on NORMAL windows of the train split; windows never cross a scenario boundary
  3. score the validation split; choose the threshold on validation only (anomaly_eval.select_threshold_segments)
  4. score the test split once (anomaly_eval.OneShotEvaluator) with that threshold
  5. save the candidate (models/candidates/anomaly/<model_id>/), register it as status ``candidate``, write the
     evaluation under reports/anomaly_candidates/<model_id>/, and record a T24 run (reports/runs/<run_id>/)

It never promotes. Promotion is ``scripts/registry_cli.py promote`` from a clean-tree run (see the notes in the
run report). The config's ``caps_status`` must be ``preregistered`` before the test split is read.
Everything reported concerns SYNTHETIC injected anomalies; nothing here says anything about real faults.
Needs TensorFlow (the detector); the pure helpers below do not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from numpy.lib.stride_tricks import sliding_window_view  # noqa: E402

from src import anomaly_eval as ae  # noqa: E402

EXPERIMENT_NAME = "anomaly_train_eval"
CANDIDATE_SUBDIR = Path("models") / "candidates" / "anomaly"
EVAL_SUBDIR = Path("reports") / "anomaly_candidates"
FEATURES = ["water_flow_lpm", "water_pressure_bar", "server_outlet_temp_C", "it_power_kw", "humidity_pct"]
SPLIT_FILES = {"train": "train.csv", "validation": "val.csv", "test": "test.csv"}
REQUIRED_CONFIG = (
    "name",
    "caps_status",
    "seed",
    "seq_len",
    "cadence_s",
    "tolerance_rows",
    "k_gap",
    "false_alarm_cap_per_day",
    "max_alert_row_fraction",
    "training",
)


class TrainingError(RuntimeError):
    """A stop condition: the run cannot proceed without inventing something."""


# ----------------------------------------------------------------------------- config
def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_CONFIG if k not in cfg]
    if missing:
        raise TrainingError(f"config is missing {missing}")
    for key in ("seed", "seq_len", "tolerance_rows", "k_gap"):
        if isinstance(cfg[key], bool) or int(cfg[key]) != cfg[key]:
            raise TrainingError(f"config.{key} must be an integer")
    for key in ("epochs", "batch_size", "validation_split", "patience"):
        if key not in cfg["training"]:
            raise TrainingError(f"config.training.{key} is required")
    return cfg


def config_core(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """What identifies the training setup (excludes prose and the owner's sign-off flag)."""
    return {k: v for k, v in cfg.items() if k not in ("description", "caps_status", "proposed_fields")}


def config_hash8(cfg: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(config_core(cfg)).encode("utf-8")).hexdigest()[:8]


def candidate_version(cfg: Mapping[str, Any]) -> str:
    return f"v2-c{config_hash8(cfg)}-s{int(cfg['seed'])}"


def candidate_model_id(cfg: Mapping[str, Any]) -> str:
    return f"{cfg['name']}-{candidate_version(cfg)}"


def require_preregistered(cfg: Mapping[str, Any]) -> None:
    if cfg["caps_status"] != "preregistered":
        raise TrainingError(
            f"caps_status is {cfg['caps_status']!r}: the false-alarm cap, alert-row cap and K are the implementer's "
            "proposal. Review them and set caps_status to 'preregistered' BEFORE the run; the test split is not read until then."
        )


# ----------------------------------------------------------------------------- dataset
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Dataset:
    directory: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    frames: dict[str, pd.DataFrame]
    events: dict[str, dict[str, list[ae.Event]]]  # split -> scenario_id -> events


def verify_dataset(directory: Path, *, allow_synthetic_inputs: bool = False) -> tuple[dict[str, Any], str]:
    directory = Path(directory)
    mpath = directory / "manifest.json"
    if not mpath.is_file():
        raise TrainingError(f"{mpath} does not exist (run scripts/make_datasets.py first)")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != directory.name:
        raise TrainingError(f"manifest dataset_id {manifest.get('dataset_id')!r} != directory name {directory.name!r}")
    for name, meta in manifest.get("files", {}).items():
        path = directory / name
        if not path.is_file():
            raise TrainingError(f"dataset file {name} is missing")
        if sha256_file(path) != meta["sha256"]:
            raise TrainingError(f"dataset file {name} does not match its manifest sha256")
    synthetic = manifest.get("synthetic_inputs") or []
    if synthetic and not allow_synthetic_inputs:
        raise TrainingError(
            f"the dataset contains synthetic inputs {synthetic}; pass --allow-synthetic-inputs to proceed (it is recorded)"
        )
    return manifest, sha256_file(mpath)


def split_scenarios(df: pd.DataFrame, cadence_s: float) -> dict[str, pd.DataFrame]:
    """scenario_id -> its rows in file order. Each scenario must be a regular series at ``cadence_s``."""
    for col in ["scenario_id", "timestamp", "anomaly", *FEATURES]:
        if col not in df.columns:
            raise TrainingError(f"dataset is missing column {col!r}")
    out: dict[str, pd.DataFrame] = {}
    for sid, frame in df.groupby("scenario_id", sort=True):
        frame = frame.reset_index(drop=True)
        steps = pd.to_datetime(frame["timestamp"]).diff().dropna().dt.total_seconds()
        if len(steps):
            stream = float(steps.iloc[0])
            if not (steps == stream).all():
                raise TrainingError(f"scenario {sid}: timestamps are not a regular series")
            ae.check_cadence(cadence_s, stream)  # raises CadenceMismatchError (a stop condition)
        out[str(sid)] = frame
    return out


def load_dataset(
    directory: Path,
    cadence_s: float,
    *,
    allow_synthetic_inputs: bool = False,
    splits: Sequence[str] = ("train", "validation", "test"),
) -> Dataset:
    manifest, msha = verify_dataset(directory, allow_synthetic_inputs=allow_synthetic_inputs)
    directory = Path(directory)
    frames = {s: pd.read_csv(directory / SPLIT_FILES[s], dtype={"scenario_id": str}) for s in splits}
    events: dict[str, dict[str, list[ae.Event]]] = {}
    records = pd.read_csv(directory / "events.csv", dtype={"scenario_id": str}).to_dict("records")
    for s in splits:
        if s != "train":
            events[s] = ae.events_from_records(records, split=SPLIT_FILES[s].split(".")[0])
    return Dataset(directory, manifest, msha, frames, events)


# ----------------------------------------------------------------------------- windows and scores
def windows_of(frame: pd.DataFrame, seq_len: int) -> tuple[np.ndarray, np.ndarray]:
    """(windows, has_anomaly) for ONE scenario: window i covers rows i..i+seq_len-1 and ends at row i+seq_len-1."""
    data = frame[FEATURES].to_numpy(dtype=np.float32)
    n = len(data)
    if n < seq_len:
        return np.empty((0, seq_len, len(FEATURES)), dtype=np.float32), np.empty(0, dtype=bool)
    win = sliding_window_view(data, (seq_len, len(FEATURES)))[:, 0]
    labels = frame["anomaly"].to_numpy()
    has_anomaly = sliding_window_view(labels, seq_len).max(axis=1) > 0
    return np.ascontiguousarray(win), has_anomaly


def normal_windows(scenarios: Mapping[str, pd.DataFrame], seq_len: int) -> np.ndarray:
    parts = []
    for frame in scenarios.values():
        win, bad = windows_of(frame, seq_len)
        if len(win):
            parts.append(win[~bad])
    if not parts or sum(len(p) for p in parts) == 0:
        raise TrainingError("no normal training windows")
    return np.concatenate(parts)


def score_scenario(detector: Any, frame: pd.DataFrame, seq_len: int) -> np.ndarray:
    """Per-row scores for one scenario: the score of the window ENDING at that row; the first seq_len-1 rows are NaN."""
    scores = np.full(len(frame), np.nan, dtype=float)
    win, _ = windows_of(frame, seq_len)
    if len(win):
        scores[seq_len - 1 :] = np.asarray(detector.score_sequences(win), dtype=float)
    return scores


def build_segments(
    detector: Any,
    scenarios: Mapping[str, pd.DataFrame],
    events_by_scenario: Mapping[str, Sequence[ae.Event]],
    seq_len: int,
) -> list[ae.Segment]:
    scores = {sid: score_scenario(detector, frame, seq_len) for sid, frame in scenarios.items()}
    return ae.segments_from_scores(scores, events_by_scenario)


# ----------------------------------------------------------------------------- data limits
INVENTORY_REF = "TWINGRID_LLM_DATASET_CONTEXT.md"


def data_limits(manifest: Mapping[str, Any]) -> list[str]:
    """What the evidence does NOT cover, recorded with every evaluation (evaluation.json, EVALUATION.md, run notes).

    Facts about the raw inputs come from the dataset inventory (``TWINGRID_LLM_DATASET_CONTEXT.md``); statements
    about the pipeline come from the code. Items marked NOT VERIFIED are open and are not resolved by this run.
    """
    limits = [
        "Workload (utilisation) is synthetic and every event is a synthetically injected anomaly from the generator's event table.",
        f"Weather inputs are Open-Meteo hourly exports for 2025 only ({INVENTORY_REF}); the generator linearly interpolates them to 5-minute rows. "
        "No statement about other years is made.",
        "NOT VERIFIED: the time zone of the Open-Meteo timestamp column. The ingestion labels it UTC (it parses with utc=True). "
        "If the exports are local time, weather is shifted against the synthetic workload cycle, which affects the humidity and outlet-temperature features.",
        "The water-stress input is an Aqueduct baseline risk score, not a measured water quantity.",
        "No benchmark dataset (NAB, ASHRAE, C-MAPSS, cluster traces) was used for training, threshold selection or evaluation; no result from one is claimed here.",
    ]
    synthetic = list(manifest.get("synthetic_inputs") or [])
    if synthetic:
        limits.append(f"Synthetic inputs were substituted for real ones: {', '.join(sorted(map(str, synthetic)))}.")
    return limits


def render_limits(limits: Sequence[str]) -> str:
    return "\n## Data limits\n\n" + "\n".join(f"* {item}" for item in limits) + "\n"


# ----------------------------------------------------------------------------- protocol
def run_protocol(detector: Any, ds: Dataset, cfg: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    """Train on normal train windows, choose the threshold on validation, evaluate test once. Pure of I/O."""
    seq_len = int(cfg["seq_len"])
    cadence = float(cfg["cadence_s"])
    ecfg = ae.EvalConfig(cadence_s=cadence, k_gap=int(cfg["k_gap"]), tolerance_rows=int(cfg["tolerance_rows"]))
    train_sc = split_scenarios(ds.frames["train"], cadence)
    val_sc = split_scenarios(ds.frames["validation"], cadence)
    train = cfg["training"]

    windows = normal_windows(train_sc, seq_len)
    history = detector.train_sequences(
        windows,
        epochs=int(train["epochs"]),
        batch_size=int(train["batch_size"]),
        validation_split=float(train["validation_split"]),
        patience=int(train["patience"]),
        seed=int(cfg["seed"]),
    )
    val_segments = build_segments(detector, val_sc, ds.events["validation"], seq_len)
    choice = ae.select_threshold_segments(
        val_segments,
        ecfg,
        split_id=ae.VALIDATION_SPLIT,
        false_alarm_cap_per_day=float(cfg["false_alarm_cap_per_day"]),
        max_alert_row_fraction=float(cfg["max_alert_row_fraction"]),
    )
    detector.set_threshold(choice.threshold, fit_split_id=ae.VALIDATION_SPLIT, input_cadence_s=cadence)

    # The test split is read only now, after the threshold exists.
    test_sc = split_scenarios(ds.frames["test"], cadence)
    test_segments = build_segments(detector, test_sc, ds.events["test"], seq_len)
    result = ae.OneShotEvaluator(run_id).evaluate_test_segments(test_segments, choice, ecfg)
    result["data_limits"] = data_limits(ds.manifest)
    result["training"] = {
        "n_train_windows": int(len(windows)),
        "epochs_run": len(history.get("loss", [])) if isinstance(history, Mapping) else None,
        "final_val_loss": (history.get("val_loss") or [None])[-1] if isinstance(history, Mapping) else None,
    }
    return result


# ----------------------------------------------------------------------------- T24 experiment
def _na(v: Any) -> Any:
    return "n/a" if v is None else v


def _experiment(config: dict[str, Any], seeds: list[int], rng_factory: Any) -> dict[str, Any]:
    """Pure summary of the evaluation already written for this candidate (no clock, no randomness, no writes)."""
    from src.repro import RESULTS_SCHEMA

    model_id = candidate_model_id(config)
    result = json.loads((REPO_ROOT / EVAL_SUBDIR / model_id / "evaluation.json").read_text(encoding="utf-8"))
    rec, prec, delay = result["event_recall"], result["event_precision"], result["detection_delay"]

    def ci(p: dict[str, Any]) -> tuple[Any, Any]:
        if p["value"] is None:
            return "n/a", "n/a"
        return p["ci95"][0], p["ci95"][1]

    rows = [
        ["event recall", _na(rec["value"]), *ci(rec), rec["successes"], rec["n"]],
        ["event precision", _na(prec["value"]), *ci(prec), prec["successes"], prec["n"]],
    ]
    type_rows = [
        [t, v["n_events"], _na(v["event_recall"]["value"]) if v["reported"] else "not reported (too few events)"]
        for t, v in result["per_type"].items()
    ]
    return {
        "schema": RESULTS_SCHEMA,
        "experiment": EXPERIMENT_NAME,
        "title": "Anomaly detector v2 (T26): event-level evaluation on synthetic injected anomalies",
        "seeds": list(seeds),
        "summary": {
            "model_id": model_id,
            "n_test_events": result["n_events"],
            "event_recall": _na(rec["value"]),
            "event_recall_ci95_low": ci(rec)[0],
            "event_recall_ci95_high": ci(rec)[1],
            "false_alarm_episodes_per_simulated_day": result["false_alarm_episodes_per_simulated_day"],
            "median_detection_delay_minutes": _na(delay["median_minutes"]),
            "threshold": result["threshold"],
            "claim": ae.claim_sentence(result),
        },
        "tables": {
            "event_level": {
                "title": "Event-level proportions (Wilson 95 % intervals)",
                "columns": ["metric", "value", "ci95_low", "ci95_high", "successes", "n"],
                "rows": rows,
            },
            "per_type": {
                "title": "Event recall per injected type",
                "columns": ["type", "n_events", "event_recall"],
                "rows": type_rows,
            },
        },
        "figures": {},
        "notes": [
            "Synthetic injected anomalies only; nothing here concerns real faults.",
            "The threshold was chosen on the validation split under the configured false-alarm and alert-row caps; the test split was evaluated once.",
            f"Config caps_status at run time: {config.get('caps_status')!r}. Row-level figures are in evaluation.json and are diagnostic only.",
            "Candidate only: promotion is scripts/registry_cli.py promote from a clean-tree run; this script never promotes.",
            *[f"Data limit: {item}" for item in result.get("data_limits", [])],
        ],
    }


# ----------------------------------------------------------------------------- main
def _rel(path: Path) -> str:
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset-dir", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "configs" / "anomaly" / "anomaly_v2.json")
    ap.add_argument("--allow-synthetic-inputs", action="store_true")
    ap.add_argument("--run-id")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        require_preregistered(cfg)
        ds = load_dataset(args.dataset_dir, float(cfg["cadence_s"]), allow_synthetic_inputs=args.allow_synthetic_inputs)
        model_id, version = candidate_model_id(cfg), candidate_version(cfg)
        cand_dir = REPO_ROOT / CANDIDATE_SUBDIR / model_id
        if cand_dir.exists():
            raise TrainingError(f"{cand_dir} already exists; candidates are never overwritten")
        run_id = args.run_id or f"anomaly-train-c{config_hash8(cfg)}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"

        from src import model_registry as mr
        from src.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector(seq_len=int(cfg["seq_len"]), feature_columns=FEATURES, verbose=0)
        result = run_protocol(detector, ds, cfg, run_id)
        result["dataset_id"] = ds.manifest["dataset_id"]
        result["synthetic_inputs"] = ds.manifest.get("synthetic_inputs", [])

        detector.save(cand_dir)
        eval_dir = REPO_ROOT / EVAL_SUBDIR / model_id
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "evaluation.json").write_text(ae.canonical_json(result) + "\n", encoding="utf-8", newline="\n")
        report_text = ae.render_report(result) + render_limits(result["data_limits"])
        if ae.find_bare_recall(report_text):
            raise TrainingError("report text contains a bare 'recall'")
        (eval_dir / "EVALUATION.md").write_text(report_text, encoding="utf-8", newline="\n")

        entry = mr.log_model(
            cfg["name"],
            version=version,
            kind="anomaly",
            status="candidate",
            metrics={
                "claim": ae.claim_sentence(result),
                "evaluation": f"{EVAL_SUBDIR.as_posix()}/{model_id}/evaluation.json",
                "threshold": result["threshold"],
                "fit_split_id": ae.VALIDATION_SPLIT,
                "input_cadence_s": float(cfg["cadence_s"]),
                "data_limits": result["data_limits"],
                "note": "candidate only; not promoted. The T19 compatibility waiver on the previous artifact is removed only by promotion.",
            },
            data_source=_rel(ds.directory),
            artifact_path=str(cand_dir),
            params={k: v for k, v in config_core(cfg).items()},
            seeds=[int(cfg["seed"])],
            scenario_set_id=ds.manifest["scenario_set_id"],
            split_id=ds.manifest["split_id"],
            dataset_id=ds.manifest["dataset_id"],
            dataset_sha256=ds.manifest_sha256,
            dataset_manifest_sha256=ds.manifest_sha256,
            physics_version=ds.manifest["physics_version"],
        )
        if entry["model_id"] != model_id:
            raise TrainingError(f"registry assigned {entry['model_id']!r}, expected {model_id!r}")
        (cand_dir / "manifest.json").write_text(
            json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )

        from src.repro import experiments
        from src.repro.run import RunRequest, run

        experiments.register(EXPERIMENT_NAME, _experiment, replace=True)
        outcome = run(
            RunRequest(
                experiment=EXPERIMENT_NAME,
                config_paths=[_rel(args.config)],
                seeds=[int(cfg["seed"])],
                dataset_manifest=_rel(ds.directory / "manifest.json"),
                artifacts=[model_id],
                scenario_set_id=ds.manifest["scenario_set_id"],
                split_id=ds.manifest["split_id"],
                run_id=run_id,
                argv=tuple(sys.argv),
            ),
            REPO_ROOT,
        )
    except (TrainingError, ae.AnomalyEvalError) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"candidate {model_id}\nrun {outcome.run_id}: {outcome.state}")
    print(ae.claim_sentence(result))
    return 0 if outcome.state == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
