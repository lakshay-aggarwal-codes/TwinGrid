"""T26 -- src/anomaly_eval.py (roadmap 13.4). NumPy only; no TensorFlow, no sklearn, no database.

Hand-built label/alert sequences with exactly known answers, the contract's stop conditions, the validation-only
threshold rule, the one-look test split, and the "no bare recall" report lint. These tests verify the METRIC CODE.
They say nothing about any detector's quality: the scores used are synthetic fixtures.
"""

from __future__ import annotations

import ast
import inspect
import json
import math

import numpy as np
import pytest

from src import anomaly_eval as ae
from src.anomaly_eval import (
    CadenceMismatchError,
    EvalConfig,
    Event,
    InsufficientEventsError,
    LeakageError,
    NoFeasibleThresholdError,
    OneShotEvaluator,
    Segment,
    SplitReuseError,
    alert_episodes,
    check_cadence,
    evaluate,
    evaluate_segments,
    find_bare_recall,
    render_report,
    select_threshold,
    select_threshold_segments,
    wilson_interval,
)

CFG = EvalConfig(cadence_s=300.0, k_gap=3, tolerance_rows=2)


def scores_with_alerts(n, rows, value=1.0):
    s = np.zeros(n)
    for r in rows:
        s[r] = value
    return s


def ev(i, t, a, b):
    return Event(f"e{i}", t, a, b)


# ===================================================================== hand-built exact cases
class TestExactMetrics:
    """40 rows, 3 events, K=3, tolerance 2, alerts at {6, 8, 12, 13, 15, 33}.

    episodes: [6,8] (gap 1<3), [12,15] (gaps 0,1), [33,33]            -> 3 episodes
    detection windows: e1 [5,9], e2 [20,24], e3 [30,32]
    [6,8] overlaps e1 (TP); [12,15] overlaps nothing (FP); [33,33] is one row past e3's window (FP)
    """

    events = [ev(1, "spike", 5, 7), ev(2, "drift", 20, 22), ev(3, "spike", 30, 30)]
    alerts = [6, 8, 12, 13, 15, 33]

    def run(self, **kw):
        return evaluate(
            scores_with_alerts(40, self.alerts),
            self.events,
            0.5,
            kw.pop("cfg", CFG),
            split_id="t",
            enforce_minimum=False,
        )

    def test_episodes(self):
        assert alert_episodes(np.array(self.alerts), 3) == [(6, 8), (12, 15), (33, 33)]

    def test_event_recall_and_delay(self):
        r = self.run()
        assert (r["event_recall"]["successes"], r["event_recall"]["n"]) == (1, 3)
        assert r["event_recall"]["value"] == pytest.approx(1 / 3)
        assert r["detection_delay"]["median_rows"] == 1.0 and r["detection_delay"]["median_minutes"] == 5.0
        assert r["detection_delay"]["n_detected"] == 1

    def test_false_positive_episodes_and_rate(self):
        r = self.run()
        assert (r["alert_episodes"], r["false_positive_episodes"]) == (3, 2)
        assert r["simulated_days"] == pytest.approx(40 * 300 / 86400)
        assert r["false_alarm_episodes_per_simulated_day"] == pytest.approx(2 / (40 * 300 / 86400))
        assert r["event_precision"]["value"] == pytest.approx(1 / 3)

    def test_row_level_is_separate_and_labelled(self):
        rl = self.run()["row_level"]
        assert "row-level" in rl["label"] and "diagnostic" in rl["label"]
        assert (rl["label_rows"], rl["alert_rows"]) == (7, 6)
        assert rl["row_recall"]["successes"] == 1 and rl["row_precision"]["successes"] == 1
        assert rl["row_f1"] == pytest.approx(2 / 13)

    def test_wider_k_merges_episodes(self):
        r = self.run(cfg=EvalConfig(300.0, 4, 2))  # gap 8->12 is 3 rows (<4): [6,15] is one episode
        assert r["alert_episodes"] == 2 and r["false_positive_episodes"] == 1
        assert r["event_precision"]["value"] == pytest.approx(1 / 2)

    def test_wider_tolerance_catches_the_late_alert(self):
        r = self.run(cfg=EvalConfig(300.0, 3, 3))  # e3 window becomes [30,33]
        assert r["event_recall"]["successes"] == 2 and r["false_positive_episodes"] == 1

    def test_json_roundtrip(self):
        r = self.run()
        assert json.loads(ae.canonical_json(r))["n_events"] == 3


class TestDetectionRules:
    def one(self, alert_rows, start=10, end=12, tol=3, n=60):
        return evaluate(
            scores_with_alerts(n, alert_rows),
            [ev(1, "x", start, end)],
            0.5,
            EvalConfig(300.0, 1, tol),
            split_id="t",
            enforce_minimum=False,
        )

    def test_alert_at_start_has_zero_delay(self):
        r = self.one([10])
        assert r["event_recall"]["successes"] == 1 and r["detection_delay"]["median_rows"] == 0.0

    def test_window_end_is_inclusive_and_one_past_is_not(self):
        assert self.one([15])["event_recall"]["successes"] == 1  # end 12 + tol 3
        assert self.one([16])["event_recall"]["successes"] == 0

    def test_an_alert_before_the_event_does_not_detect_it(self):
        r = self.one([9])
        assert r["event_recall"]["successes"] == 0 and r["false_positive_episodes"] == 1

    def test_delay_is_the_first_alert_in_the_window(self):
        assert self.one([11, 12, 13])["detection_delay"]["median_rows"] == 1.0

    def test_no_alerts_gives_zero_recall_no_episodes_no_delay(self):
        r = self.one([])
        assert r["event_recall"]["value"] == 0.0 and r["alert_episodes"] == 0
        assert r["event_precision"]["value"] is None and r["detection_delay"]["median_minutes"] is None
        assert r["false_alarm_episodes_per_simulated_day"] == 0.0

    def test_threshold_is_inclusive(self):
        s = np.zeros(30)
        s[10] = 0.7
        got = evaluate(s, [ev(1, "x", 10, 10)], 0.7, EvalConfig(300.0, 1, 0), split_id="t", enforce_minimum=False)
        assert got["event_recall"]["successes"] == 1

    def test_nan_scores_are_not_alerts_and_are_counted(self):
        s = scores_with_alerts(30, [10])
        s[:5] = np.nan
        r = evaluate(s, [ev(1, "x", 10, 10)], 0.5, EvalConfig(300.0, 1, 0), split_id="t", enforce_minimum=False)
        assert r["n_unscored_rows"] == 5 and r["event_recall"]["successes"] == 1
        allnan = evaluate(
            np.full(30, np.nan), [ev(1, "x", 10, 10)], 0.0, EvalConfig(300.0, 1, 0), split_id="t", enforce_minimum=False
        )
        assert allnan["alert_episodes"] == 0

    def test_median_and_iqr_of_delays(self):
        events = [ev(i, "x", 20 * i, 20 * i + 2) for i in range(1, 6)]
        alert_rows = [20 * i + d for i, d in zip(range(1, 6), (0, 1, 2, 3, 4))]
        r = evaluate(
            scores_with_alerts(130, alert_rows),
            events,
            0.5,
            EvalConfig(300.0, 1, 5),
            split_id="t",
            enforce_minimum=False,
        )
        d = r["detection_delay"]
        assert (d["median_rows"], d["iqr_rows"]) == (2.0, [1.0, 3.0]) and d["median_minutes"] == 10.0


class TestEventShapes:
    def test_invalid_events_are_rejected(self):
        for a, b in ((5, 4), (-1, 3)):
            with pytest.raises(ae.AnomalyEvalError):
                Event("x", "t", a, b)

    def test_event_beyond_the_scored_rows_is_rejected(self):
        with pytest.raises(ae.AnomalyEvalError):
            evaluate(np.zeros(10), [ev(1, "x", 8, 12)], 0.5, CFG, split_id="t", enforce_minimum=False)

    def test_inf_scores_are_rejected(self):
        with pytest.raises(ae.AnomalyEvalError):
            evaluate(np.array([0.0, np.inf]), [], 0.5, CFG, split_id="t", enforce_minimum=False)

    @pytest.mark.parametrize(
        "kw", [{"cadence_s": 0.0}, {"cadence_s": float("nan")}, {"k_gap": 0}, {"tolerance_rows": -1}]
    )
    def test_bad_config_is_rejected(self, kw):
        base = dict(cadence_s=300.0, k_gap=3, tolerance_rows=2)
        base.update(kw)
        with pytest.raises(ae.AnomalyEvalError):
            EvalConfig(**base)


# ===================================================================== statistics
class TestWilson:
    def test_known_values(self):
        lo, hi = wilson_interval(0, 30)
        assert lo == 0.0 and hi == pytest.approx(0.1135, abs=5e-4)
        lo, hi = wilson_interval(30, 30)
        assert hi == pytest.approx(1.0) and lo == pytest.approx(0.8865, abs=5e-4)
        lo, hi = wilson_interval(15, 30)
        assert (lo, hi) == (pytest.approx(0.3315, abs=5e-4), pytest.approx(0.6685, abs=5e-4))

    def test_matches_the_closed_form(self):
        z, k, n = ae.WILSON_Z_95, 7, 40
        p = k / n
        centre = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        assert wilson_interval(k, n) == (pytest.approx(centre - half), pytest.approx(centre + half))

    def test_contains_the_point_estimate_and_stays_in_unit_interval(self):
        for n in (1, 5, 30, 200):
            for k in range(0, n + 1, max(1, n // 7)):
                lo, hi = wilson_interval(k, n)
                assert 0.0 <= lo <= k / n <= hi <= 1.0

    def test_empty_and_invalid(self):
        assert wilson_interval(0, 0) == (0.0, 1.0)
        for k, n in ((-1, 5), (6, 5)):
            with pytest.raises(ae.AnomalyEvalError):
                wilson_interval(k, n)


# ===================================================================== stop conditions
class TestStopConditions:
    def events_of(self, n):
        return [ev(i, "spike" if i % 2 else "drift", 10 * i, 10 * i + 2) for i in range(n)]

    def test_fewer_than_30_events_is_an_error_not_a_warning(self):
        with pytest.raises(InsufficientEventsError):
            evaluate(np.zeros(1000), self.events_of(29), 0.5, CFG, split_id="test")
        r = evaluate(np.zeros(1000), self.events_of(30), 0.5, CFG, split_id="test")
        assert r["n_events"] == 30

    def test_cadence_mismatch_is_an_error(self):
        check_cadence(300.0, 300.0)
        with pytest.raises(CadenceMismatchError):
            check_cadence(300.0, 60.0)

    def test_per_type_figures_need_five_events(self):
        events = self.events_of(30)[:28] + [ev(90, "rare", 400, 402), ev(91, "rare", 410, 412)]
        r = evaluate(np.zeros(1000), events, 0.5, CFG, split_id="test")
        assert r["per_type"]["rare"] == {"reported": False, "n_events": 2, "reason": "fewer than 5 events"}
        assert r["per_type"]["spike"]["reported"] and "event_recall" in r["per_type"]["spike"]


# ===================================================================== threshold rule (validation only)
class TestThresholdSelection:
    def fixture(self):
        """100 events x 20-row blocks. Event i is hit at score (i / 100); noise rows between events are low."""
        n_ev, stride = 60, 20
        n = n_ev * stride
        scores = np.zeros(n)
        events = []
        for i in range(n_ev):
            start = i * stride + 2
            events.append(ev(i, "spike" if i % 2 else "drift", start, start + 2))
            scores[start + 1] = 0.5 + 0.5 * (i + 1) / n_ev  # peak score of event i, in (0.5, 1.0]
        # three isolated false-alarm bursts of score 0.6 (rows far from events)
        for row in (7, 407, 807):
            scores[row] = 0.6
        return scores, events

    cfg = EvalConfig(cadence_s=300.0, k_gap=3, tolerance_rows=2)

    def test_max_recall_under_the_false_alarm_cap(self):
        scores, events = self.fixture()
        days = len(scores) * 300 / 86400
        loose = select_threshold(
            scores,
            events,
            self.cfg,
            split_id="validation",
            false_alarm_cap_per_day=10 / days,
            max_alert_row_fraction=0.25,
        )
        tight = select_threshold(
            scores, events, self.cfg, split_id="validation", false_alarm_cap_per_day=0.0, max_alert_row_fraction=0.25
        )
        # loose cap: the 3 isolated bursts (0.72 false alarms/day) are affordable, so the threshold drops to the
        # LOWEST event peak (0.5 + 0.5/60) and every event is found.
        assert loose.validation_false_alarms_per_day == pytest.approx(3 / days)
        assert loose.threshold == pytest.approx(0.5 + 0.5 / 60)
        assert loose.validation_event_recall == 1.0
        # cap 0: the threshold must clear the 0.6 bursts; events 12..59 peak above that -> 48 of 60 found,
        # and the tie rule keeps the highest threshold that achieves it (the peak of event 12).
        assert tight.validation_false_alarms_per_day == 0.0
        assert tight.threshold == pytest.approx(0.5 + 0.5 * 13 / 60)
        assert tight.validation_event_recall == pytest.approx(48 / 60)

    def test_tie_goes_to_the_higher_threshold(self):
        scores = scores_with_alerts(600, [], 0.0)
        events = [ev(i, "x", 20 * i + 2, 20 * i + 3) for i in range(30)]
        for e in events:
            scores[e.start] = 0.9
        scores[599] = 0.3  # a lower candidate that adds one false alarm but no recall
        choice = select_threshold(
            scores,
            events,
            EvalConfig(300.0, 3, 2),
            split_id="validation",
            false_alarm_cap_per_day=1e9,
            max_alert_row_fraction=0.25,
        )
        assert choice.threshold == 0.9 and choice.validation_event_recall == 1.0

    def test_infeasible_cap_raises_and_is_never_relaxed(self):
        events = [ev(i, "x", 10 * i + 2, 10 * i + 3) for i in range(30)]
        scores = np.zeros(400)
        for e in events:
            scores[e.start] = 0.5
        scores[390] = 0.99  # the global maximum sits far from every event: every threshold alerts there -> FP >= 1
        with pytest.raises(NoFeasibleThresholdError, match="not relaxed"):
            select_threshold(
                scores,
                events,
                EvalConfig(300.0, 3, 2),
                split_id="validation",
                false_alarm_cap_per_day=0.0,
                max_alert_row_fraction=0.5,
            )
        # ... while a cap that admits that one episode is feasible, proving the error was about the cap
        ok = select_threshold(
            scores,
            events,
            EvalConfig(300.0, 3, 2),
            split_id="validation",
            false_alarm_cap_per_day=1.0 / (400 * 300 / 86400),
            max_alert_row_fraction=0.5,
        )
        assert ok.validation_event_recall == 1.0

    def test_all_nan_validation_scores_have_no_threshold(self):
        events = [ev(i, "x", 10 * i + 2, 10 * i + 3) for i in range(30)]
        with pytest.raises(NoFeasibleThresholdError):
            select_threshold(
                np.full(400, np.nan),
                events,
                EvalConfig(300.0, 3, 2),
                split_id="validation",
                false_alarm_cap_per_day=5.0,
                max_alert_row_fraction=0.5,
            )

    def test_only_validation_is_accepted(self):
        scores, events = self.fixture()
        for split in ("test", "train", "", "Validation"):
            with pytest.raises(LeakageError):
                select_threshold(
                    scores, events, self.cfg, split_id=split, false_alarm_cap_per_day=1.0, max_alert_row_fraction=0.25
                )

    def test_an_always_alerting_threshold_is_not_a_solution(self):
        """Without the row-fraction cap, threshold 0 (alert everywhere) = ONE episode overlapping events:
        recall 1.0 with zero false-alarm episodes. The rule must exclude it."""
        events = [ev(i, "x", 10 * i + 2, 10 * i + 3) for i in range(30)]
        scores = np.zeros(400)
        for e in events:
            scores[e.start] = 0.5
        scores[390] = 0.99
        always = evaluate(scores, events, 0.0, EvalConfig(300.0, 3, 2), split_id="validation")
        assert always["event_recall"]["value"] == 1.0 and always["false_positive_episodes"] == 0  # the loophole
        with pytest.raises(NoFeasibleThresholdError):
            select_threshold(
                scores,
                events,
                EvalConfig(300.0, 3, 2),
                split_id="validation",
                false_alarm_cap_per_day=0.0,
                max_alert_row_fraction=0.5,
            )

    @pytest.mark.parametrize("frac", [0.0, 1.0, -0.1, float("nan"), 2.0])
    def test_the_row_fraction_cap_must_be_a_real_fraction(self, frac):
        scores, events = self.fixture()
        with pytest.raises(ae.AnomalyEvalError):
            select_threshold(
                scores,
                events,
                self.cfg,
                split_id="validation",
                false_alarm_cap_per_day=1.0,
                max_alert_row_fraction=frac,
            )

    def test_choice_records_both_caps_and_what_was_achieved(self):
        scores, events = self.fixture()
        c = select_threshold(
            scores, events, self.cfg, split_id="validation", false_alarm_cap_per_day=100.0, max_alert_row_fraction=0.25
        )
        assert c.max_alert_row_fraction == 0.25 and 0.0 < c.validation_alert_row_fraction <= 0.25
        assert c.fit_split_id == "validation"

    def test_api_has_no_way_to_receive_test_rows(self):
        params = set(inspect.signature(select_threshold).parameters)
        assert not any("test" in p for p in params) and params >= {"val_scores", "val_events", "split_id"}
        tree = ast.parse(inspect.getsource(select_threshold))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert not any("test" in n.lower() for n in names)

    def test_selection_is_deterministic_and_enforces_the_event_minimum(self):
        scores, events = self.fixture()
        a = select_threshold(
            scores, events, self.cfg, split_id="validation", false_alarm_cap_per_day=5.0, max_alert_row_fraction=0.25
        )
        b = select_threshold(
            scores.copy(),
            list(events),
            self.cfg,
            split_id="validation",
            false_alarm_cap_per_day=5.0,
            max_alert_row_fraction=0.25,
        )
        assert a == b
        with pytest.raises(InsufficientEventsError):
            select_threshold(
                scores,
                events[:10],
                self.cfg,
                split_id="validation",
                false_alarm_cap_per_day=5.0,
                max_alert_row_fraction=0.25,
            )

    def test_candidates_are_thinned_deterministically(self):
        rng = np.random.default_rng(0)
        scores = rng.random(5000)
        events = [ev(i, "x", 100 * i + 5, 100 * i + 6) for i in range(40)]
        c = select_threshold(
            scores,
            events,
            EvalConfig(300.0, 3, 2),
            split_id="validation",
            false_alarm_cap_per_day=1e9,
            max_alert_row_fraction=0.5,
            max_candidates=100,
        )
        assert c.candidates_considered <= 100


# ===================================================================== test split is looked at once
class TestOneShot:
    def data(self):
        events = [ev(i, "spike" if i % 2 else "drift", 20 * i + 2, 20 * i + 4) for i in range(30)]
        scores = np.zeros(600)
        for e in events:
            scores[e.start + 1] = 1.0
        return scores, events

    def choice(self, split="validation"):
        return ae.ThresholdChoice(0.5, split, "rule", 1.0, 0.25, 1.0, 0.0, 0.05, 10)

    def test_second_look_is_refused(self):
        scores, events = self.data()
        ev_ = OneShotEvaluator("run-1")
        r = ev_.evaluate_test(scores, events, self.choice(), EvalConfig(300.0, 3, 2))
        assert r["split_id"] == "test" and r["run_id"] == "run-1" and r["event_recall"]["value"] == 1.0
        assert r["threshold_choice"]["fit_split_id"] == "validation"
        with pytest.raises(SplitReuseError):
            ev_.evaluate_test(scores, events, self.choice(), EvalConfig(300.0, 3, 2))

    def test_threshold_fitted_elsewhere_is_refused_without_consuming_the_look(self):
        scores, events = self.data()
        ev_ = OneShotEvaluator("run-2")
        with pytest.raises(LeakageError):
            ev_.evaluate_test(scores, events, self.choice("test"), EvalConfig(300.0, 3, 2))
        assert ev_.evaluate_test(scores, events, self.choice(), EvalConfig(300.0, 3, 2))["n_events"] == 30

    def test_a_failed_evaluation_still_consumes_the_look(self):
        scores, events = self.data()
        ev_ = OneShotEvaluator("run-3")
        with pytest.raises(InsufficientEventsError):
            ev_.evaluate_test(scores, events[:5], self.choice(), EvalConfig(300.0, 3, 2))
        with pytest.raises(SplitReuseError):
            ev_.evaluate_test(scores, events, self.choice(), EvalConfig(300.0, 3, 2))

    def test_run_id_is_required(self):
        with pytest.raises(ae.AnomalyEvalError):
            OneShotEvaluator("")


# ===================================================================== report text lint
class TestReportLint:
    @pytest.mark.parametrize(
        "text",
        [
            "Event recall 0.9",
            "event recall",
            "Event-level recall",
            "Row-level recall 0.4",
            "row recall",
            "no such word",
            "",
        ],
    )
    def test_qualified_or_absent_is_clean(self, text):
        assert find_bare_recall(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "Recall 0.97",
            "the recall was high",
            "precision and recall",
            "Detection recall",
            "recall",
        ],
    )
    def test_bare_recall_is_found(self, text):
        assert find_bare_recall(text)

    def test_every_rendered_report_is_clean_and_carries_its_label_and_claim(self):
        events = [ev(i, "spike" if i % 2 else "drift", 20 * i + 2, 20 * i + 4) for i in range(30)]
        scores = np.zeros(620)
        for e in events[:20]:
            scores[e.start + 1] = 1.0
        r = evaluate(scores, events, 0.5, EvalConfig(300.0, 3, 2), split_id="test")
        text = render_report(r)
        assert find_bare_recall(text) == []
        assert "synthetic injected anomalies" in text.lower() and "Row-level (diagnostic only)" in text
        assert "Event recall:" in text and "Row-level recall:" in text
        assert "median detection delay" in text and "false-alarm episodes per simulated day" in text
        assert ae.claim_sentence(r) in text

    def test_report_with_no_detections_still_renders(self):
        events = [ev(i, "x", 20 * i + 2, 20 * i + 4) for i in range(30)]
        text = render_report(evaluate(np.zeros(620), events, 0.5, EvalConfig(300.0, 3, 2), split_id="test"))
        assert "n/a" in text and find_bare_recall(text) == []


# ===================================================================== end-to-end self-test of the code path
class TestPipelineSelfTest:
    """Threshold on validation, one look at test, report. Synthetic scores: this exercises the CODE, and its
    numbers are not evidence about any detector."""

    @staticmethod
    def make(seed, n_events=40, rows=4000):
        rng = np.random.default_rng(seed)
        scores = rng.normal(0.0, 1.0, rows)
        events = []
        stride = rows // n_events
        for i in range(n_events):
            s = i * stride + 10
            events.append(ev(i, ("spike", "drift", "stuck")[i % 3], s, s + 3))
            scores[s : s + 4] += 4.0
        return scores, events

    def test_full_flow_is_deterministic_and_respects_the_cap(self):
        cfg = EvalConfig(300.0, 3, 6)
        vs, ve = self.make(1)
        ts, te = self.make(2)
        cap = 3.0
        choice = select_threshold(
            vs, ve, cfg, split_id="validation", false_alarm_cap_per_day=cap, max_alert_row_fraction=0.2
        )
        assert choice.validation_false_alarms_per_day <= cap
        r1 = OneShotEvaluator("a").evaluate_test(ts, te, choice, cfg)
        r2 = OneShotEvaluator("b").evaluate_test(ts, te, choice, cfg)
        r1.pop("run_id")
        r2.pop("run_id")
        assert ae.canonical_json(r1) == ae.canonical_json(r2)
        assert 0.0 <= r1["event_recall"]["value"] <= 1.0
        lo, hi = r1["event_recall"]["ci95"]
        assert lo <= r1["event_recall"]["value"] <= hi
        assert find_bare_recall(render_report(r1)) == []


# ===================================================================== segments (T25: one segment per scenario)
class TestSegments:
    """A split is a set of independent scenarios: nothing may merge or detect across a boundary."""

    cfg = EvalConfig(cadence_s=300.0, k_gap=5, tolerance_rows=3)

    def test_episodes_do_not_merge_across_a_boundary(self):
        a = Segment("s1", scores_with_alerts(20, [19]), (ev(1, "x", 18, 19),))
        b = Segment("s2", scores_with_alerts(20, [0]), (ev(2, "x", 0, 1),))
        seg = evaluate_segments([a, b], 0.5, self.cfg, split_id="t", enforce_minimum=False)
        assert seg["alert_episodes"] == 2 and seg["event_recall"]["successes"] == 2
        # the SAME rows concatenated into one series would be a single episode: that is the bug being prevented
        joined = evaluate(
            scores_with_alerts(40, [19, 20]),
            [ev(1, "x", 18, 19), ev(2, "x", 20, 21)],
            0.5,
            self.cfg,
            split_id="t",
            enforce_minimum=False,
        )
        assert joined["alert_episodes"] == 1

    def test_a_detection_window_does_not_reach_into_the_next_segment(self):
        a = Segment("s1", scores_with_alerts(20, []), (ev(1, "x", 17, 19),))  # window would reach rows 20..22
        b = Segment("s2", scores_with_alerts(20, [0, 1]), ())
        r = evaluate_segments([a, b], 0.5, self.cfg, split_id="t", enforce_minimum=False)
        assert r["event_recall"]["successes"] == 0 and r["false_positive_episodes"] == 1
        joined = evaluate(
            scores_with_alerts(40, [20, 21]), [ev(1, "x", 17, 19)], 0.5, self.cfg, split_id="t", enforce_minimum=False
        )
        assert joined["event_recall"]["successes"] == 1  # what a naive concatenation would have claimed

    def test_event_free_segments_still_count_for_false_alarms_and_days(self):
        clean = Segment("clean", scores_with_alerts(100, [50]), ())
        ev_seg = Segment("evt", scores_with_alerts(100, [11]), (ev(1, "x", 10, 12),))
        r = evaluate_segments([clean, ev_seg], 0.5, self.cfg, split_id="t", enforce_minimum=False)
        assert r["n_segments"] == 2 and r["n_rows"] == 200
        assert r["simulated_days"] == pytest.approx(200 * 300 / 86400)
        assert (r["alert_episodes"], r["false_positive_episodes"]) == (2, 1)
        assert r["false_alarm_episodes_per_simulated_day"] == pytest.approx(1 / (200 * 300 / 86400))

    def test_aggregation_equals_the_sum_of_the_parts(self):
        parts = [
            Segment("a", scores_with_alerts(60, [6, 30]), (ev(1, "spike", 5, 7), ev(2, "drift", 40, 42))),
            Segment("b", scores_with_alerts(60, [20]), (ev(3, "spike", 19, 21),)),
            Segment("c", scores_with_alerts(60, []), (ev(4, "drift", 10, 11),)),
        ]
        whole = evaluate_segments(parts, 0.5, self.cfg, split_id="t", enforce_minimum=False)
        singles = [evaluate_segments([p], 0.5, self.cfg, split_id="t", enforce_minimum=False) for p in parts]
        assert whole["n_events"] == sum(s["n_events"] for s in singles) == 4
        assert whole["event_recall"]["successes"] == sum(s["event_recall"]["successes"] for s in singles) == 2
        assert whole["alert_episodes"] == sum(s["alert_episodes"] for s in singles)
        assert whole["false_positive_episodes"] == sum(s["false_positive_episodes"] for s in singles)
        assert whole["row_level"]["alert_rows"] == sum(s["row_level"]["alert_rows"] for s in singles)
        assert whole["detection_delay"]["n_detected"] == 2

    def test_one_segment_equals_the_single_series_api(self):
        scores = scores_with_alerts(40, [6, 8, 12, 13, 15, 33])
        events = [ev(1, "spike", 5, 7), ev(2, "drift", 20, 22), ev(3, "spike", 30, 30)]
        one = evaluate(scores, events, 0.5, CFG, split_id="t", enforce_minimum=False)
        seg = evaluate_segments(
            [Segment("series", scores, tuple(events))], 0.5, CFG, split_id="t", enforce_minimum=False
        )
        assert ae.canonical_json(one) == ae.canonical_json(seg)

    def test_per_type_events_are_pooled_across_segments(self):
        segs = [Segment(f"s{i}", scores_with_alerts(50, [11]), (ev(i, "spike", 10, 12),)) for i in range(5)]
        r = evaluate_segments(segs, 0.5, self.cfg, split_id="t", enforce_minimum=False)
        assert r["per_type"]["spike"]["reported"] and r["per_type"]["spike"]["n_events"] == 5

    def test_duplicate_segment_ids_and_event_ids_are_rejected(self):
        s = scores_with_alerts(30, [])
        with pytest.raises(ae.AnomalyEvalError, match="duplicate segment"):
            evaluate_segments([Segment("a", s), Segment("a", s)], 0.5, CFG, split_id="t", enforce_minimum=False)
        with pytest.raises(ae.AnomalyEvalError, match="unique"):
            evaluate_segments(
                [Segment("a", s, (ev(1, "x", 1, 2),)), Segment("b", s, (ev(1, "x", 1, 2),))],
                0.5,
                CFG,
                split_id="t",
                enforce_minimum=False,
            )
        with pytest.raises(ae.AnomalyEvalError):
            evaluate_segments([], 0.5, CFG, split_id="t", enforce_minimum=False)

    def test_event_minimum_counts_events_over_all_segments(self):
        segs = [Segment(f"s{i}", scores_with_alerts(40, []), (ev(i, "x", 5, 6),)) for i in range(29)]
        with pytest.raises(InsufficientEventsError):
            evaluate_segments(segs, 0.5, self.cfg, split_id="test")
        segs.append(Segment("s29", scores_with_alerts(40, []), (ev(29, "x", 5, 6),)))
        assert evaluate_segments(segs, 0.5, self.cfg, split_id="test")["n_events"] == 30

    def test_threshold_selection_over_segments_matches_the_pooled_rule(self):
        segs = []
        for i in range(40):
            sc = np.zeros(60)
            sc[11] = 0.4 + 0.01 * i  # event peak
            segs.append(Segment(f"v{i}", sc, (ev(i, "x", 10, 12),)))
        noisy = np.zeros(60)
        noisy[50] = 0.45  # one isolated false alarm in the last segment
        segs[-1] = Segment("v39", np.where(np.arange(60) == 50, 0.45, segs[-1].scores), segs[-1].events)
        days = 40 * 60 * 300 / 86400
        loose = select_threshold_segments(
            segs, self.cfg, split_id="validation", false_alarm_cap_per_day=2 / days, max_alert_row_fraction=0.2
        )
        tight = select_threshold_segments(
            segs, self.cfg, split_id="validation", false_alarm_cap_per_day=0.0, max_alert_row_fraction=0.2
        )
        assert loose.validation_event_recall == 1.0 and loose.threshold == pytest.approx(0.4)
        assert tight.validation_false_alarms_per_day == 0.0 and tight.validation_event_recall < 1.0
        assert tight.threshold > 0.45

    def test_threshold_selection_never_merges_across_segments_either(self):
        # alert on the last row of one segment and the first row of the next: two episodes, not one
        segs = [
            Segment(f"v{i}", scores_with_alerts(30, [29, 0] if i else [0]), (ev(i, "x", 14, 15),)) for i in range(30)
        ]
        with pytest.raises(NoFeasibleThresholdError):
            select_threshold_segments(
                segs, self.cfg, split_id="validation", false_alarm_cap_per_day=0.0, max_alert_row_fraction=0.5
            )

    def test_segment_threshold_selection_is_validation_only(self):
        segs = [Segment("v", scores_with_alerts(50, []), tuple(ev(i, "x", 2 * i, 2 * i) for i in range(30)))]
        for split in ("test", "train"):
            with pytest.raises(LeakageError):
                select_threshold_segments(
                    segs, self.cfg, split_id=split, false_alarm_cap_per_day=1.0, max_alert_row_fraction=0.5
                )

    def test_one_shot_over_segments(self):
        segs = [Segment(f"t{i}", scores_with_alerts(40, [11]), (ev(i, "x", 10, 12),)) for i in range(30)]
        choice = ae.ThresholdChoice(0.5, "validation", "rule", 1.0, 0.25, 1.0, 0.0, 0.05, 10)
        e = OneShotEvaluator("r")
        r = e.evaluate_test_segments(segs, choice, self.cfg)
        assert r["split_id"] == "test" and r["n_segments"] == 30 and r["event_recall"]["value"] == 1.0
        with pytest.raises(SplitReuseError):
            e.evaluate_test_segments(segs, choice, self.cfg)


# ===================================================================== T25 event-table adapter
T25_HEADER = "event_id,scenario_id,split,type,start,end,start_idx,end_idx,params\n"


class TestEventTableAdapter:
    def rec(self, eid="train-0-E00", sid="train-0", split="train", typ="leak", a=588, b=601):
        return {"event_id": eid, "scenario_id": sid, "split": split, "type": typ, "start_idx": a, "end_idx": b}

    def test_half_open_indices_become_inclusive(self):
        out = ae.events_from_records([self.rec(a=10, b=13)])
        (e,) = out["train-0"]
        assert (e.start, e.end) == (10, 12)  # rows 10, 11, 12 -- exactly the 3 rows of [10, 13)

    def test_a_one_row_event(self):
        (e,) = ae.events_from_records([self.rec(a=7, b=8)])["train-0"]
        assert (e.start, e.end) == (7, 7)

    def test_grouped_by_scenario_and_filtered_by_split(self):
        recs = [
            self.rec("a", "s1", "test", "leak", 1, 3),
            self.rec("b", "s1", "test", "thermal", 5, 9),
            self.rec("c", "s2", "val", "leak", 2, 4),
        ]
        assert {k: len(v) for k, v in ae.events_from_records(recs).items()} == {"s1": 2, "s2": 1}
        assert list(ae.events_from_records(recs, split="test")) == ["s1"]

    def test_the_conversion_matches_the_t25_row_labels(self):
        """T25 labels rows start_idx..end_idx-1 as anomalous; the converted event covers exactly those rows."""
        n, a, b = 30, 8, 14
        label = np.zeros(n, dtype=bool)
        label[a:b] = True
        (e,) = ae.events_from_records([self.rec(a=a, b=b)])["train-0"]
        covered = np.zeros(n, dtype=bool)
        covered[e.start : e.end + 1] = True
        assert (covered == label).all()
        # the oracle scorer (score = label) therefore detects it immediately with no false alarms
        r = evaluate(label.astype(float), [e], 0.5, EvalConfig(300.0, 3, 6), split_id="t", enforce_minimum=False)
        assert r["event_recall"]["value"] == 1.0 and r["detection_delay"]["median_rows"] == 0.0
        assert r["false_positive_episodes"] == 0 and r["row_level"]["row_f1"] == pytest.approx(1.0)

    @pytest.mark.parametrize("bad", [dict(a=5, b=5), dict(a=9, b=4), dict(a=-1, b=3), dict(a="x", b=3)])
    def test_bad_ranges_are_rejected(self, bad):
        with pytest.raises(ae.AnomalyEvalError):
            ae.events_from_records([self.rec(**bad)])

    def test_missing_columns_and_duplicates_are_rejected(self):
        r = self.rec()
        r.pop("end_idx")
        with pytest.raises(ae.AnomalyEvalError, match="missing column"):
            ae.events_from_records([r])
        with pytest.raises(ae.AnomalyEvalError, match="duplicate"):
            ae.events_from_records([self.rec(), self.rec()])

    def test_load_events_csv_reads_the_t25_layout(self, tmp_path):
        path = tmp_path / "events.csv"
        path.write_text(
            T25_HEADER
            + 'train-0-E00,train-0,train,leak,2025-03-18T01:00:00,2025-03-18T02:05:00,588,601,"{""center_idx"":594}"\n'
            + 'test-9-E01,test-9,test,thermal,2025-03-17T03:25:00,2025-03-17T04:10:00,329,338,"{""spike_C"":11.8}"\n',
            encoding="utf-8",
        )
        all_ = ae.load_events_csv(path)
        assert set(all_) == {"train-0", "test-9"}
        (e,) = ae.load_events_csv(path, split="test")["test-9"]
        assert (e.event_id, e.type, e.start, e.end) == ("test-9-E01", "thermal", 329, 337)

    def test_segments_from_scores(self):
        events = {"s2": [ev(1, "x", 1, 2)]}
        segs = ae.segments_from_scores({"s2": np.zeros(10), "s1": np.zeros(10)}, events)
        assert [s.segment_id for s in segs] == ["s1", "s2"] and segs[0].events == () and len(segs[1].events) == 1
        with pytest.raises(ae.AnomalyEvalError, match="without scores"):
            ae.segments_from_scores({"s1": np.zeros(10)}, events)

    def test_required_columns_exist_in_the_t25_event_table(self):
        """If T25's pipeline is present, the columns this adapter reads must still be in its event table."""
        import importlib

        try:
            dp = importlib.import_module("src.data_pipeline")
        except ImportError:
            pytest.skip("T25 (src/data_pipeline.py) is not in this tree")
        assert set(ae.REQUIRED_EVENT_COLUMNS) <= set(dp.EVENT_COLUMNS)
