"""Task 19: forecaster evaluation core. Pure NumPy; no TensorFlow, no network, no trained model.

``_ConstantLearner`` is a TEST DOUBLE (predicts the training mean). It exists only here, to exercise the learned-model
code path and the verdict rule; it is not a forecaster and no number it produces is reported anywhere.
"""

from __future__ import annotations

import json
import re

import numpy as np
import pytest

from src import forecast_eval as fe

N = 3000


def _series(seed: int = 0):
    rng = np.random.default_rng(seed)
    t = np.arange(N)
    util = 0.5 + 0.3 * np.sin(2 * np.pi * t / fe.SEASON_STEPS) + 0.02 * rng.normal(size=N)
    y = 30 + 8 * util + 0.2 * rng.normal(size=N)
    feats = np.column_stack(
        [util if c == fe.UTIL else (y if c == fe.TARGET else rng.normal(size=N) + 5) for c in fe.FEATURES]
    )
    return feats, y


class _ConstantLearner:
    name = "constant_test_double"

    def fit_predict(self, x_train, y_train, x_test, *, seed, horizon):
        return np.full(len(x_test), float(y_train.mean()))


def test_split_is_row_disjoint_for_every_horizon():
    s = fe.make_split(N)
    for h in (1, 3, 6):
        tr, te = s.origins("train", h), s.origins("test", h)
        assert tr.max() + h < te.min() - s.seq_len + 1
        assert te.max() + h == N - 1
        assert s.origins("val", h).min() >= s.val_start + s.seq_len - 1


def test_windows_never_include_rows_after_the_origin():
    feats, _ = _series()
    o = np.array([100, 500])
    w = fe.windows(feats, o)
    assert w.shape == (2, fe.SEQ_LEN, len(fe.FEATURES))
    assert np.array_equal(w[0, -1], feats[100])


def test_baselines_on_known_series():
    y = np.tile(np.arange(fe.SEASON_STEPS, dtype=float), 4)
    o = np.arange(fe.SEASON_STEPS + 10, 3 * fe.SEASON_STEPS)
    for h in (1, 6):
        assert np.allclose(fe.predict_seasonal_naive(y, o, h), y[o + h])
        assert np.allclose(fe.predict_seasonal_delta(y, o, h), y[o + h])
    assert np.allclose(fe.predict_persistence(y, o, 3), y[o])
    c = np.full(50, 7.0)
    assert np.allclose(fe.predict_moving_average(c, np.arange(20, 40), 1, window=6), 7.0)


def test_seasonal_baselines_refuse_missing_history():
    y = np.arange(100.0)
    with pytest.raises(fe.ForecastEvalError):
        fe.predict_seasonal_naive(y, np.array([50]), 1)


def test_leakage_checks_pass_on_clean_data():
    feats, y = _series()
    checks = fe.leakage_checks(feats, y, fe.make_split(N), (1, 3, 6))
    assert {c["name"] for c in checks} >= {
        "train_windows_never_touch_test_rows",
        "scaler_fitted_on_train_rows_only",
        "predictions_ignore_rows_after_the_origin",
    }
    assert all(c["passed"] for c in checks), checks


def test_scramble_method_separates_a_future_reader_from_a_causal_predictor():
    feats, y = _series()
    t = np.array([1500])
    h = 3
    y2 = y.copy()
    y2[t[0] + 1 :] = 1e3
    peek = lambda arr: arr[t + h]  # noqa: E731  (reads the target row itself)
    assert not np.allclose(peek(y), peek(y2))  # a leaky predictor changes when the future changes
    assert np.allclose(fe.predict_persistence(y, t, h), fe.predict_persistence(y2, t, h))


def test_block_bootstrap_is_deterministic_and_in_range():
    a = fe.block_indices(500, 72, 50, np.random.default_rng(1))
    b = fe.block_indices(500, 72, 50, np.random.default_rng(1))
    assert a.shape == (50, 500) and np.array_equal(a, b) and a.min() >= 0 and a.max() < 500


def test_verdict_rule():
    assert fe.verdict([-0.2, -0.05]) == "model_better"
    assert fe.verdict([0.05, 0.2]) == "model_worse"
    assert fe.verdict([-0.1, 0.1]) == "inconclusive"
    assert fe.verdict(None) == "unevaluated"


def test_regime_thresholds_come_from_train_rows_only():
    feats, y = _series()
    s = fe.make_split(N)
    o = s.origins("test", 6)
    base = fe.regimes(feats, s, o)
    f2 = feats.copy()
    f2[s.train_end :, fe.FEATURES.index(fe.UTIL)] += 5.0  # change test rows only
    shifted = fe.regimes(f2, s, o)
    assert base["utilisation_high"].sum() < shifted["utilisation_high"].sum() == len(o)


def test_run_without_learner_is_baselines_only_and_unevaluated():
    feats, y = _series()
    r = fe.run_evaluation(feats, y, fe.RunConfig(boot_reps=50))
    assert r["learned_model_status"].startswith("not_run")
    assert r["horizons"]["6"]["verdict"] == "unevaluated"
    assert r["horizons"]["1"]["verdict"] == "baselines_only"
    assert set(r["horizons"]["6"]["models"]) == set(fe.BASELINES)
    assert all(c["passed"] for c in r["leakage_checks"])
    assert len(r["split"]["hashes"]["test_rows"]) == 64


def test_learned_path_needs_five_seeds_and_reports_every_seed():
    feats, y = _series()
    with pytest.raises(fe.ForecastEvalError):
        fe.run_evaluation(feats, y, fe.RunConfig(seeds=(0, 1, 2), boot_reps=20), learner=_ConstantLearner())
    r = fe.run_evaluation(feats, y, fe.RunConfig(boot_reps=100), learner=_ConstantLearner())
    e = r["horizons"]["6"]
    m = e["models"]["constant_test_double"]
    assert [s["seed"] for s in m["seeds"]] == [0, 1, 2, 3, 4]
    assert e["verdict"] == "model_worse"  # a constant cannot beat the best baseline on a diurnal series
    assert e["best_baseline"] in fe.BASELINES
    assert all(
        "constant_test_double" not in r["horizons"][k]["models"] for k in ("1", "3")
    )  # learned at horizon 6 only


def test_same_inputs_give_identical_results():
    feats, y = _series()
    cfg = fe.RunConfig(boot_reps=40)
    a, b = fe.run_evaluation(feats, y, cfg), fe.run_evaluation(feats, y, cfg)
    for r in (a, b):
        r.pop("created_at_utc")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_report_and_card_evidence_format():
    feats, y = _series()
    r = fe.run_evaluation(feats, y, fe.RunConfig(boot_reps=30), learner=_ConstantLearner())
    text = fe.render_report(r)
    assert "simulator data only" in text and "PASS" in text and "FAIL" not in text
    pat = re.compile(r"^- EVIDENCE (?P<label>\S+) = (?P<value>.+?) \| (?P<file>\S+) \| (?P<path>\S+)\s*$")
    lines = fe.card_evidence(r).splitlines()
    assert lines and all(pat.match(ln) for ln in lines)


def test_load_series_rejects_gaps_and_missing_columns(tmp_path):
    pd = pytest.importorskip("pandas")
    ts = pd.date_range("2024-01-01", periods=50, freq="5min")
    df = pd.DataFrame({c: np.arange(50.0) for c in fe.FEATURES})
    df.insert(0, "timestamp", ts)
    ok = tmp_path / "ok.csv"
    df.to_csv(ok, index=False)
    assert len(fe.load_series(ok)) == 50
    df.drop(index=10).to_csv(tmp_path / "gap.csv", index=False)
    with pytest.raises(fe.ForecastEvalError):
        fe.load_series(tmp_path / "gap.csv")
    df.drop(columns=[fe.TARGET]).to_csv(tmp_path / "col.csv", index=False)
    with pytest.raises(fe.ForecastEvalError):
        fe.load_series(tmp_path / "col.csv")


def test_cli_baselines_only_writes_outputs(tmp_path):
    pd = pytest.importorskip("pandas")
    feats, y = _series()
    df = pd.DataFrame(feats, columns=list(fe.FEATURES))
    df.insert(0, "timestamp", pd.date_range("2024-01-01", periods=N, freq="5min"))
    csv = tmp_path / "s.csv"
    df.to_csv(csv, index=False)
    out = tmp_path / "out"
    assert fe.main(["--csv", str(csv), "--baselines-only", "--out", str(out)]) == 0
    res = json.loads((out / "results.json").read_text())
    assert res["dataset"]["rows"] == N and (out / "REPORT.md").exists() and (out / "CARD_EVIDENCE.txt").exists()
    assert fe.main(["--csv", str(tmp_path / "nope.csv"), "--baselines-only", "--out", str(out)]) == 2


def test_protocol_file_exists_and_names_the_decision_rule():
    text = fe.PROTOCOL_PATH.read_text(encoding="utf-8")
    for token in ("model_better", "model_worse", "inconclusive", "unevaluated", "block"):
        assert token in text
