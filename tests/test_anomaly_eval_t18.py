"""Task 18 (ML-003): protocol lock, rolling z-score baseline, cluster bootstrap, event F1, and the one-shot run driver.

Everything runs on hand-built numbers and a tiny generated dataset. No TensorFlow, no real detector: the scorers used here
are fixtures, so these tests verify the EVALUATION MACHINERY, not any model's quality.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import anomaly_eval as ae
from src.anomaly_eval import EvalConfig, Event, ProtocolError, Segment

ROOT = Path(__file__).resolve().parent.parent
REAL_PROTOCOL_DIR = ROOT / "reports" / "anomaly_eval"
REAL_CONFIG = json.loads((ROOT / "configs" / "anomaly" / "anomaly_v2.json").read_text(encoding="utf-8"))
CFG = EvalConfig(cadence_s=300.0, k_gap=3, tolerance_rows=6)
FEATURES = list(ae.FEATURES)


# --------------------------------------------------------------------------------------------- baseline scorer
def _naive_zscore(x: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for t in range(window, len(x)):
        ref = x[t - window : t]
        mean, std = ref.mean(axis=0), ref.std(axis=0)
        floor = 1e-3 * np.maximum(np.abs(mean), 1.0)
        out[t] = (np.abs(x[t] - mean) / np.maximum(std, floor)).max()
    return out


def test_rolling_zscore_matches_a_plain_loop_and_leaves_the_warmup_unscored():
    rng = np.random.default_rng(3)
    x = rng.normal(10.0, 2.0, size=(120, 5))
    got = ae.rolling_zscore_scores(x, 24)
    want = _naive_zscore(x, 24)
    assert np.isnan(got[:24]).all() and not np.isnan(got[24:]).any()
    assert np.allclose(got[24:], want[24:], rtol=1e-9, atol=1e-9)


def test_a_spike_is_not_part_of_its_own_reference_and_a_constant_feature_stays_finite():
    x = np.zeros((60, 2))
    x[:, 0] = np.tile([1.0, -1.0], 30)  # std 1, mean ~0
    x[40, 0] = 30.0
    scores = ae.rolling_zscore_scores(x, 24)
    assert scores[40] > 20.0  # the spike is judged against the rows before it
    assert np.isfinite(scores[24:]).all()  # feature 1 is constant: the floor prevents inf


def test_rolling_zscore_rejects_a_tiny_window_and_short_series_are_all_unscored():
    with pytest.raises(ae.AnomalyEvalError):
        ae.rolling_zscore_scores(np.zeros((10, 1)), 1)
    assert np.isnan(ae.rolling_zscore_scores(np.zeros((10, 1)), 24)).all()


# ------------------------------------------------------------------------------------------------- event F1
def test_event_f1_cases():
    assert ae.event_f1(1.0, 1.0) == 1.0
    assert ae.event_f1(0.5, 1.0) == pytest.approx(2 * 0.5 / 1.5)
    assert ae.event_f1(0.0, 0.0) == 0.0
    assert ae.event_f1(None, 0.5) is None and ae.event_f1(0.5, None) is None


# ----------------------------------------------------------------------------------------- bootstrap and pairing
def _segments(n: int = 12, hit_every: int = 1) -> list[Segment]:
    """n scenarios of 100 rows, two events each; an event is 'hit' by a high score on its first row, else missed.
    Every third scenario also carries one false alarm at row 90."""
    segs = []
    for i in range(n):
        scores = np.zeros(100)
        events = (Event(f"s{i}-a", "leak", 20, 24), Event(f"s{i}-b", "thermal", 50, 54))
        if i % hit_every == 0:
            scores[22] = 9.0
            scores[52] = 9.0
        if i % 3 == 0:
            scores[90] = 9.0
        segs.append(Segment(f"s{i:02d}", scores, events))
    return segs


def test_bootstrap_point_estimates_equal_the_metric_core():
    segs = _segments(hit_every=2)
    boot = ae.bootstrap_metrics(segs, 5.0, CFG, reps=50, seed=1)
    core = ae.evaluate_segments(segs, 5.0, CFG, split_id="test", enforce_minimum=False)
    assert boot["event_recall"]["value"] == pytest.approx(core["event_recall"]["value"])
    assert boot["event_precision"]["value"] == pytest.approx(core["event_precision"]["value"])
    assert boot["false_alarm_episodes_per_day"]["value"] == pytest.approx(
        core["false_alarm_episodes_per_simulated_day"]
    )
    assert boot["median_delay_minutes"]["value"] == pytest.approx(core["detection_delay"]["median_minutes"])
    r, p = core["event_recall"]["value"], core["event_precision"]["value"]
    assert boot["event_f1"]["value"] == pytest.approx(2 * r * p / (r + p))
    for t, v in boot["recall_by_type"].items():
        assert v["value"] == pytest.approx(core["per_type"][t]["event_recall"]["value"])


def test_the_bootstrap_is_deterministic_in_its_seed_and_collapses_when_every_scenario_is_alike():
    segs = _segments()
    a = ae.bootstrap_metrics(segs, 5.0, CFG, reps=80, seed=7)
    b = ae.bootstrap_metrics(segs, 5.0, CFG, reps=80, seed=7)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    uniform = [
        Segment(f"u{i}", np.where(np.arange(100) == 22, 9.0, 0.0), (Event(f"u{i}-a", "leak", 20, 24),))
        for i in range(10)
    ]
    lo, hi = ae.bootstrap_metrics(uniform, 5.0, CFG, reps=60, seed=2)["event_recall"]["ci95"]
    assert lo == hi == 1.0


def test_the_interval_brackets_the_point_estimate_on_mixed_scenarios():
    segs = _segments(n=30, hit_every=2)
    b = ae.bootstrap_metrics(segs, 5.0, CFG, reps=400, seed=11)["event_recall"]
    assert 0.0 < b["value"] < 1.0 and b["ci95"][0] <= b["value"] <= b["ci95"][1] and b["ci95"][0] < b["ci95"][1]


def test_a_paired_difference_is_zero_for_the_same_scorer_and_clearly_positive_for_a_better_one():
    good = _segments(n=20)
    none = _segments(n=20, hit_every=10**9)  # i=0 still hits; make the rest miss
    for s in none:
        if s.segment_id != "s00":
            s.scores[:] = 0.0
    same = ae.paired_bootstrap_difference(good, 5.0, good, 5.0, CFG, reps=100, seed=5)
    assert (
        same["a_minus_b"] == 0.0
        and same["ci95"] == [0.0, 0.0]
        and not same["a_clearly_better"]
        and not same["b_clearly_better"]
    )
    diff = ae.paired_bootstrap_difference(good, 5.0, none, 5.0, CFG, reps=200, seed=5)
    assert diff["a_minus_b"] > 0 and diff["a_clearly_better"] and not diff["b_clearly_better"]
    flipped = ae.paired_bootstrap_difference(none, 5.0, good, 5.0, CFG, reps=200, seed=5)
    assert flipped["b_clearly_better"]


def test_pairing_requires_the_same_scenarios_in_the_same_order():
    segs = _segments(n=4)
    other = [
        Segment(f"x{i}", s.scores, tuple(Event(f"x{i}-{k}", e.type, e.start, e.end) for k, e in enumerate(s.events)))
        for i, s in enumerate(segs)
    ]
    with pytest.raises(ae.AnomalyEvalError):
        ae.paired_bootstrap_difference(segs, 5.0, other, 5.0, CFG, reps=5)


def test_the_conclusion_follows_the_decision_rule_and_never_claims_more():
    base = {"metric": "event_f1", "n_valid_reps": 100}
    win = ae.conclusion(
        "autoencoder",
        "rolling_zscore",
        {**base, "a_minus_b": 0.2, "ci95": [0.1, 0.3], "a_clearly_better": True, "b_clearly_better": False},
    )
    lose = ae.conclusion(
        "autoencoder",
        "rolling_zscore",
        {**base, "a_minus_b": -0.2, "ci95": [-0.3, -0.1], "a_clearly_better": False, "b_clearly_better": True},
    )
    tie = ae.conclusion(
        "autoencoder",
        "rolling_zscore",
        {**base, "a_minus_b": 0.05, "ci95": [-0.1, 0.2], "a_clearly_better": False, "b_clearly_better": False},
    )
    none = ae.conclusion(
        "autoencoder",
        "rolling_zscore",
        {**base, "a_minus_b": None, "ci95": None, "a_clearly_better": False, "b_clearly_better": False},
    )
    assert win.startswith("autoencoder beat rolling_zscore") and "synthetic" in win
    assert lose.startswith("rolling_zscore beat autoencoder") and "WORSE" in lose
    assert tie.startswith("NO DEMONSTRATED ADVANTAGE") and "includes 0" in tie
    assert none.startswith("INSUFFICIENT")


# --------------------------------------------------------------------------------------------- protocol lock
def _copy_protocol(tmp: Path) -> Path:
    d = tmp / "proto"
    d.mkdir()
    shutil.copy(REAL_PROTOCOL_DIR / ae.PROTOCOL_FILE, d / ae.PROTOCOL_FILE)
    ae.lock_protocol(d)
    return d


def _cfg() -> dict:
    return {**REAL_CONFIG, "caps_status": "preregistered"}


def test_the_committed_protocol_hash_matches_the_committed_text_and_the_config(tmp_path):
    """Tripwire: editing PROTOCOL.md or the caps in the config without re-locking (before the test run) fails here."""
    record = json.loads((REAL_PROTOCOL_DIR / ae.PROTOCOL_HASH_FILE).read_text(encoding="utf-8"))
    assert record["protocol_sha256"] == ae.protocol_sha256(REAL_PROTOCOL_DIR / ae.PROTOCOL_FILE)
    assert record["test_split_read_before_lock"] is False
    assert ae.verify_protocol(REAL_PROTOCOL_DIR, _cfg())["primary_metric"] == "event_f1"


def test_line_endings_do_not_change_the_hash(tmp_path):
    lf = tmp_path / "a.md"
    crlf = tmp_path / "b.md"
    lf.write_bytes(b"one\ntwo\n")
    crlf.write_bytes(b"one\r\ntwo\r\n")
    assert ae.protocol_sha256(lf) == ae.protocol_sha256(crlf) == hashlib.sha256(b"one\ntwo\n").hexdigest()


def test_changing_the_protocol_after_it_was_locked_is_refused(tmp_path):
    d = _copy_protocol(tmp_path)
    assert ae.verify_protocol(d, _cfg())
    (d / ae.PROTOCOL_FILE).write_text(
        (d / ae.PROTOCOL_FILE).read_text(encoding="utf-8") + "\nA late edit.\n", encoding="utf-8"
    )
    with pytest.raises(ProtocolError, match="changed after it was locked"):
        ae.verify_protocol(d, _cfg())


def test_a_missing_lock_a_config_mismatch_and_unconfirmed_caps_are_each_refused(tmp_path):
    d = tmp_path / "proto"
    d.mkdir()
    shutil.copy(REAL_PROTOCOL_DIR / ae.PROTOCOL_FILE, d / ae.PROTOCOL_FILE)
    with pytest.raises(ProtocolError, match="lock the protocol"):
        ae.verify_protocol(d, _cfg())
    ae.lock_protocol(d)
    with pytest.raises(ProtocolError, match="false_alarm_cap_per_day"):
        ae.verify_protocol(d, {**_cfg(), "false_alarm_cap_per_day": 5.0})
    with pytest.raises(ProtocolError, match="preregistered"):
        ae.verify_protocol(d, {**REAL_CONFIG})  # still PROPOSED_UNCONFIRMED


def test_the_protocol_cannot_be_locked_after_the_test_split_was_used(tmp_path):
    d = _copy_protocol(tmp_path)
    (d / ae.TEST_USED_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(ProtocolError, match="already used"):
        ae.lock_protocol(d)


# ---------------------------------------------------------------------------------------------- run driver
def _build_dataset(root: Path, *, n_val: int = 18, n_test: int = 18, effect: float = 12.0) -> Path:
    """A tiny dataset in the v2 file layout: two events per scenario, strong and easy, so a z-score rule finds them."""
    block = ae.read_prereg_block(REAL_PROTOCOL_DIR / ae.PROTOCOL_FILE)
    d = root / "ds_tiny"
    d.mkdir()
    rng = np.random.default_rng(0)
    events, frames = [], {"train": [], "val": [], "test": []}
    for split, n in (("train", 6), ("val", n_val), ("test", n_test)):
        for i in range(n):
            sid = f"{split[:2]}{i:03d}"
            values = rng.normal(10.0, 1.0, size=(300, len(FEATURES)))
            label = np.zeros(300, dtype=int)
            for k, (a, b, t) in enumerate(((60, 67, "leak"), (180, 187, "thermal"))):
                values[a:b] += effect
                label[a:b] = 1
                events.append(
                    {
                        "event_id": f"{sid}-E{k}",
                        "scenario_id": sid,
                        "split": split,
                        "type": t,
                        "start_idx": a,
                        "end_idx": b,
                    }
                )
            df = pd.DataFrame(values, columns=FEATURES)
            df.insert(0, "scenario_id", sid)
            df.insert(1, "timestamp", pd.date_range("2025-01-01", periods=300, freq="5min"))
            df["anomaly"] = label
            frames[split].append(df)
    for split, name in (("train", "train.csv"), ("val", "val.csv"), ("test", "test.csv")):
        pd.concat(frames[split]).to_csv(d / name, index=False)
    pd.DataFrame(events).to_csv(d / "events.csv", index=False)
    files = {p.name: {"sha256": ae._sha256_file(p)} for p in sorted(d.glob("*.csv"))}
    manifest = {
        "dataset_id": d.name,
        "split_id": block["dataset_split_id"],
        "scenario_set_id": block["dataset_scenario_set_id"],
        "files": files,
        "synthetic_inputs": [],
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


class FixtureScorer:
    """A stand-in for the autoencoder. ``mode``: 'same' = identical to the baseline, 'noise' = unrelated to the faults,
    'constant' = alerts everywhere (no feasible threshold). Records whether the test marker existed when a test scenario was scored."""

    def __init__(self, name: str, mode: str, protocol_dir: Path) -> None:
        self.name, self.mode, self.protocol_dir = name, mode, protocol_dir
        self.saw_marker_on_test = []
        self.fit_calls = 0

    def fit(self, train_scenarios):
        self.fit_calls += 1
        return {"fixture": True}

    def score(self, frame):
        sid = str(frame["scenario_id"].iloc[0])
        if sid.startswith("te"):
            self.saw_marker_on_test.append((self.protocol_dir / ae.TEST_USED_FILE).exists())
        if self.mode == "same":
            return ae.rolling_zscore_scores(frame[FEATURES].to_numpy(dtype=float), ae.BASELINE_WINDOW_ROWS)
        if self.mode == "constant":
            return np.ones(len(frame))
        return np.random.default_rng(abs(hash(sid)) % (2**32)).random(len(frame))


def _run(tmp: Path, mode: str, **over):
    proto = _copy_protocol(tmp)
    data = _build_dataset(tmp)
    fixture = FixtureScorer("autoencoder", mode, proto)
    kwargs = {"run_id": "t18-test", "protocol_dir": proto, "out_dir": tmp / "out", "reps": 120}
    kwargs.update(over)
    report = ae.run_final([ae.RollingZScoreScorer(), fixture], data, _cfg(), **kwargs)
    return report, proto, fixture


def test_the_baseline_alone_finds_these_easy_events_so_the_fixture_is_meaningful(tmp_path):
    report, _, _ = _run(tmp_path, "same")
    b = report["test"]["rolling_zscore"]
    assert b["scored"] and b["n_events"] == 36 and b["event_recall"]["value"] == 1.0
    assert set(b["per_type"]) == {"leak", "thermal"} and all(v["reported"] for v in b["per_type"].values())


def test_an_identical_detector_shows_no_demonstrated_advantage_and_the_outputs_are_written(tmp_path):
    report, proto, _ = _run(tmp_path, "same")
    assert report["comparison"]["conclusion"].startswith("NO DEMONSTRATED ADVANTAGE")
    assert report["comparison"]["difference"]["a_minus_b"] == 0.0
    assert report["protocol_sha256"] == ae.protocol_sha256(proto / ae.PROTOCOL_FILE)
    results = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert results["run_id"] == "t18-test" and results["test"]["autoencoder"]["bootstrap"]["reps"] == 120
    text = (tmp_path / "out" / "REPORT.md").read_text(encoding="utf-8")
    assert "synthetic injected anomalies only" in text and "NO DEMONSTRATED ADVANTAGE" in text
    assert ae.find_bare_recall(text) == []


def test_a_detector_that_is_worse_than_the_baseline_is_reported_as_worse(tmp_path):
    report, _, _ = _run(tmp_path, "noise")
    assert report["comparison"]["conclusion"].startswith("rolling_zscore beat autoencoder")
    assert report["comparison"]["difference"]["b_clearly_better"] is True


def test_a_scorer_with_no_feasible_threshold_is_not_scored_and_the_verdict_is_insufficient(tmp_path):
    report, _, _ = _run(tmp_path, "constant")
    assert report["test"]["autoencoder"]["scored"] is False and "caps" in report["test"]["autoencoder"]["reason"]
    assert report["test"]["rolling_zscore"]["scored"] is True
    assert report["comparison"]["conclusion"].startswith("INSUFFICIENT")


def test_the_test_marker_exists_before_any_test_scenario_is_scored_and_a_second_run_is_refused(tmp_path):
    report, proto, fixture = _run(tmp_path, "same")
    assert fixture.saw_marker_on_test and all(fixture.saw_marker_on_test)
    marker = json.loads((proto / ae.TEST_USED_FILE).read_text(encoding="utf-8"))
    assert marker["run_id"] == "t18-test" and marker["protocol_sha256"] == report["protocol_sha256"]
    again = FixtureScorer("autoencoder", "same", proto)
    with pytest.raises(ProtocolError, match="scored once, ever"):
        ae.run_final(
            [ae.RollingZScoreScorer(), again],
            tmp_path / "ds_tiny",
            _cfg(),
            run_id="second",
            protocol_dir=proto,
            reps=10,
        )
    assert again.fit_calls == 0  # refused before anything was fitted


def test_nothing_is_fitted_or_marked_when_the_protocol_check_fails(tmp_path):
    proto = _copy_protocol(tmp_path)
    data = _build_dataset(tmp_path)
    (proto / ae.PROTOCOL_FILE).write_text(
        (proto / ae.PROTOCOL_FILE).read_text(encoding="utf-8") + "x", encoding="utf-8"
    )
    fixture = FixtureScorer("autoencoder", "same", proto)
    with pytest.raises(ProtocolError):
        ae.run_final([ae.RollingZScoreScorer(), fixture], data, _cfg(), run_id="r", protocol_dir=proto, reps=10)
    other = tmp_path / "again"
    other.mkdir()
    good = _copy_protocol(other)
    with pytest.raises(ProtocolError, match="preregistered"):
        ae.run_final(
            [ae.RollingZScoreScorer(), fixture], data, dict(REAL_CONFIG), run_id="r", protocol_dir=good, reps=10
        )
    assert (
        fixture.fit_calls == 0 and not (proto / ae.TEST_USED_FILE).exists() and not (good / ae.TEST_USED_FILE).exists()
    )


def test_a_dataset_that_is_not_the_one_named_in_the_protocol_is_refused_before_the_test_is_marked(tmp_path):
    proto = _copy_protocol(tmp_path)
    data = _build_dataset(tmp_path)
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    manifest["split_id"] = "0" * 64
    (data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProtocolError, match="split_id"):
        ae.run_final(
            [ae.RollingZScoreScorer(), FixtureScorer("autoencoder", "same", proto)],
            data,
            _cfg(),
            run_id="r",
            protocol_dir=proto,
            reps=10,
        )
    assert not (proto / ae.TEST_USED_FILE).exists()


def test_a_tampered_dataset_file_and_undeclared_synthetic_inputs_are_refused(tmp_path):
    data = _build_dataset(tmp_path)
    with (data / "val.csv").open("a", encoding="utf-8") as fh:
        fh.write("tamper\n")
    with pytest.raises(ProtocolError, match="sha256"):
        ae.verify_dataset(data)
    second = tmp_path / "second"
    second.mkdir()
    clean = _build_dataset(second)
    manifest = json.loads((clean / "manifest.json").read_text(encoding="utf-8"))
    manifest["synthetic_inputs"] = ["weather:Delhi"]
    (clean / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProtocolError, match="synthetic"):
        ae.verify_dataset(clean)
    assert ae.verify_dataset(clean, allow_synthetic_inputs=True)["synthetic_inputs"] == ["weather:Delhi"]


def test_the_validation_stage_never_reads_the_test_file(tmp_path):
    data = _build_dataset(tmp_path)
    (data / "test.csv").unlink()  # the manifest still lists it; remove the entry so verification passes
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    del manifest["files"]["test.csv"]
    (data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    out = ae.run_validation([ae.RollingZScoreScorer()], data, _cfg())
    entry = out["scorers"]["rolling_zscore"]
    assert entry["threshold_choice"]["fit_split_id"] == "validation" and entry["validation"]["split_id"] == "validation"


def test_validation_events_below_the_minimum_stop_the_run(tmp_path):
    data = _build_dataset(tmp_path, n_val=5, n_test=5)  # 10 events each: below 30
    with pytest.raises(ae.InsufficientEventsError):
        ae.run_validation([ae.RollingZScoreScorer()], data, _cfg())
