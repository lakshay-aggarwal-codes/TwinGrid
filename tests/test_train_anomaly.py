"""T26 training protocol: pure helpers and the leakage-relevant ordering, with a stub detector (no TensorFlow)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import anomaly_eval as ae

_spec = importlib.util.spec_from_file_location(
    "train_anomaly", Path(__file__).resolve().parent.parent / "scripts" / "train_anomaly.py"
)
ta = importlib.util.module_from_spec(_spec)
sys.modules["train_anomaly"] = ta
_spec.loader.exec_module(ta)

SEQ = 12
CADENCE = 300


def make_scenario(sid: str, n: int = 400, event: tuple[int, int] | None = None) -> pd.DataFrame:
    ts = pd.date_range("2025-01-01", periods=n, freq="5min")
    df = pd.DataFrame({c: np.zeros(n) for c in ta.FEATURES})
    df.insert(0, "scenario_id", sid)
    df.insert(1, "timestamp", ts)
    df["anomaly"] = 0
    if event:
        df.loc[event[0] : event[1] - 1, "anomaly"] = 1
        df.loc[event[0] : event[1] - 1, ta.FEATURES[0]] = 10.0
    return df


class StubDetector:
    """Scores a window by the max of feature 0; records call order."""

    def __init__(self):
        self.log: list[str] = []
        self.threshold = None
        self.fit_split_id = None

    def train_sequences(self, windows, **kw):
        self.log.append("train")
        self.train_windows = windows
        return {"loss": [1.0, 0.5], "val_loss": [1.0, 0.6]}

    def score_sequences(self, windows):
        self.log.append("score")
        return windows[:, :, 0].max(axis=1)

    def set_threshold(self, value, *, fit_split_id, input_cadence_s=None):
        self.log.append("set_threshold")
        self.threshold, self.fit_split_id = value, fit_split_id


def cfg(**over):
    base = {
        "name": "anomaly_detector",
        "caps_status": "preregistered",
        "seed": 0,
        "seq_len": SEQ,
        "cadence_s": CADENCE,
        "tolerance_rows": 6,
        "k_gap": 3,
        "false_alarm_cap_per_day": 2.0,
        "max_alert_row_fraction": 0.05,
        "training": {"epochs": 1, "batch_size": 8, "validation_split": 0.2, "patience": 1},
    }
    base.update(over)
    return base


def make_dataset(n_val=35, n_test=35):
    def split_frame(prefix, k):
        frames, events = [], []
        for i in range(k):
            sid = f"{prefix}-{i}"
            frames.append(make_scenario(sid, event=(80, 84)))
            events.append(
                {
                    "event_id": f"{sid}-e",
                    "scenario_id": sid,
                    "split": prefix,
                    "type": "leak" if i % 2 else "thermal",
                    "start_idx": 80,
                    "end_idx": 84,
                }
            )
        return pd.concat(frames, ignore_index=True), events

    train = pd.concat([make_scenario(f"train-{i}", event=(80, 84)) for i in range(3)], ignore_index=True)
    val, ev_val = split_frame("val", n_val)
    test, ev_test = split_frame("test", n_test)
    return ta.Dataset(
        Path("."),
        {"dataset_id": "x"},
        "0" * 64,
        {"train": train, "validation": val, "test": test},
        {
            "validation": ae.events_from_records(ev_val, split="val"),
            "test": ae.events_from_records(ev_test, split="test"),
        },
    )


def test_windows_never_cross_scenarios_and_exclude_anomalies():
    a, b = make_scenario("a", 100, event=(40, 44)), make_scenario("b", 100)
    win, bad = ta.windows_of(a, SEQ)
    assert len(win) == 100 - SEQ + 1
    # windows touching rows 40..43 are exactly those starting at 40-SEQ+1 .. 43
    assert np.flatnonzero(bad).tolist() == list(range(40 - SEQ + 1, 44))
    normal = ta.normal_windows({"a": a, "b": b}, SEQ)
    assert len(normal) == (100 - SEQ + 1 - int(bad.sum())) + (100 - SEQ + 1)
    assert normal[:, :, 0].max() == 0.0


def test_scores_align_to_window_end_with_nan_warmup():
    det = StubDetector()
    frame = make_scenario("a", 60, event=(30, 34))
    scores = ta.score_scenario(det, frame, SEQ)
    assert np.isnan(scores[: SEQ - 1]).all() and not np.isnan(scores[SEQ - 1 :]).any()
    assert scores[29] == 0.0 and scores[30] == 10.0  # first window containing row 30 ends at row 30
    assert scores[33 + SEQ - 1] == 10.0 and scores[33 + SEQ] == 0.0


def test_short_scenario_is_fully_unscored():
    scores = ta.score_scenario(StubDetector(), make_scenario("a", SEQ - 1), SEQ)
    assert np.isnan(scores).all()


def test_cadence_mismatch_is_a_stop_condition():
    with pytest.raises(ae.CadenceMismatchError):
        ta.split_scenarios(make_scenario("a", 50), 600.0)


def test_irregular_timestamps_rejected():
    frame = make_scenario("a", 50)
    frame.loc[10, "timestamp"] = frame.loc[10, "timestamp"] + pd.Timedelta(minutes=1)
    with pytest.raises(ta.TrainingError):
        ta.split_scenarios(frame, CADENCE)


def test_protocol_orders_threshold_before_test_scoring_and_evaluates_events():
    det = StubDetector()
    result = ta.run_protocol(det, make_dataset(), cfg(), "run-1")
    i_set = det.log.index("set_threshold")
    assert det.log[0] == "train" and det.log.count("set_threshold") == 1
    assert "score" in det.log[:i_set]  # validation scored before the threshold exists
    assert det.fit_split_id == "validation"
    assert result["split_id"] == "test" and result["n_events"] == 35
    assert result["event_recall"]["value"] == 1.0
    assert result["threshold_choice"]["fit_split_id"] == "validation"
    assert ae.render_report(result)  # no bare "recall"
    assert (det.train_windows[:, :, 0] == 0).all()  # trained on normal windows only


def test_protocol_refuses_too_few_events():
    with pytest.raises(ae.InsufficientEventsError):
        ta.run_protocol(StubDetector(), make_dataset(n_val=35, n_test=5), cfg(), "run-2")


def test_infeasible_caps_raise_rather_than_relax():
    ds = make_dataset()
    with pytest.raises(ae.NoFeasibleThresholdError):
        ta.run_protocol(StubDetector(), ds, cfg(max_alert_row_fraction=0.0001), "run-3")


def test_unconfirmed_caps_block_the_run():
    with pytest.raises(ta.TrainingError):
        ta.require_preregistered(cfg(caps_status="PROPOSED_UNCONFIRMED"))
    ta.require_preregistered(cfg())


def test_candidate_identity_ignores_signoff_but_not_settings():
    a, b = cfg(), cfg(caps_status="PROPOSED_UNCONFIRMED", description="x")
    assert ta.candidate_model_id(a) == ta.candidate_model_id(b)
    assert ta.candidate_model_id(a) != ta.candidate_model_id(cfg(k_gap=5))


def _write_dataset(tmp_path: Path) -> Path:
    d = tmp_path / "abc123"
    d.mkdir()
    (d / "train.csv").write_text("a\n1\n")
    manifest = {
        "dataset_id": "abc123",
        "files": {"train.csv": {"sha256": ta.sha256_file(d / "train.csv")}},
        "synthetic_inputs": [],
    }
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


def test_dataset_verification(tmp_path):
    d = _write_dataset(tmp_path)
    manifest, sha = ta.verify_dataset(d)
    assert manifest["dataset_id"] == "abc123" and len(sha) == 64
    (d / "train.csv").write_text("a\n2\n")
    with pytest.raises(ta.TrainingError):
        ta.verify_dataset(d)


def test_dataset_dir_name_must_equal_id(tmp_path):
    d = _write_dataset(tmp_path)
    renamed = d.rename(tmp_path / "other")
    with pytest.raises(ta.TrainingError):
        ta.verify_dataset(renamed)


def test_synthetic_inputs_refused_unless_allowed(tmp_path):
    d = _write_dataset(tmp_path)
    m = json.loads((d / "manifest.json").read_text())
    m["synthetic_inputs"] = ["weather"]
    (d / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ta.TrainingError):
        ta.verify_dataset(d)
    ta.verify_dataset(d, allow_synthetic_inputs=True)


def test_experiment_results_satisfy_the_run_schema(tmp_path):
    from src.repro.report import validate_results

    c = cfg()
    result = ta.run_protocol(StubDetector(), make_dataset(), c, "run-x")
    out = tmp_path / ta.EVAL_SUBDIR / ta.candidate_model_id(c)
    out.mkdir(parents=True)
    (out / "evaluation.json").write_text(ae.canonical_json(result), encoding="utf-8")
    old = ta.REPO_ROOT
    ta.REPO_ROOT = tmp_path
    try:
        results = ta._experiment(c, [0], None)
    finally:
        ta.REPO_ROOT = old
    validate_results(results)
    assert results["summary"]["n_test_events"] == 35
    assert "recall" not in results["summary"]["claim"].replace("event recall", "")
