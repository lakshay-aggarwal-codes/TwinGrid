"""Amendment A2 (TG-A-12): the envelope's PUE limit is a counted, absolute hard constraint of the harness."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from src import policy_evaluation as pe
from src.baselines import config as bcfg
from src.baselines import evaluation as bev
from src.baselines import tuning
from src.digital_twin import PUE_MAX_SAFE, SAFETY_ENVELOPE
from tests.test_policy_evaluation import _decide

ROOT = Path(__file__).resolve().parents[1]
LEGACY_RESULTS = ROOT / "reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json"
LEGACY_RESULTS_SHA256 = "e17f1473bbad6a2db47bb31b3016eec212a1011e5a3a5aee9641504e8462c822"
PUE = "pue_over_max_steps"


# --------------------------------------------------------------------------------------- the counter
class _StubEnv:
    """Replays a fixed PUE sequence; everything else sits safely inside the envelope."""

    physics_version = "1"
    seq: list[float] = []

    def __init__(self, **kw):
        self.physics_version = kw["physics_version"]
        self._i = 0

    def _state(self, pue):
        return {
            "hour": 0.0, "utilisation": 0.5, "outside_temp": 20.0, "it_power": 100.0, "cooling_power": 10.0,
            "water_consumed": 1.0, "carbon_gco2": 1.0, "pue": pue, "wue": 0.5, "outlet_temp": 35.0, "inlet_temp": 22.0,
        }  # fmt: skip

    def reset(self, seed=None):
        return np.zeros(3), {}

    def get_state_dict(self):
        return self._state(1.2)

    def step(self, action):
        pue = self.seq[self._i]
        self._i += 1
        return np.zeros(3), 0.0, False, False, {"state": self._state(pue)}

    def close(self):
        pass


class _Pol:
    def act(self, obs, state):
        return np.zeros(2, dtype=np.float32)


def _count(monkeypatch, seq):
    _StubEnv.seq = list(seq)
    monkeypatch.setattr(pe, "DataCentreEnv", _StubEnv)
    cfg = pe.EvalConfig(episode_steps=len(seq))
    sc = pe.build_scenarios(pe.EvalConfig(n_test_per_family=1))["test"][0]
    return pe.run_episode(_Pol(), sc, cfg, np.full(24, 475.0)).metrics[PUE]


def test_the_limit_is_the_envelopes_own(monkeypatch):
    assert pe.PUE_MAX_SAFE == PUE_MAX_SAFE == SAFETY_ENVELOPE.pue_max == 2.0


def test_counts_steps_strictly_above_the_limit_and_not_at_it(monkeypatch):
    assert _count(monkeypatch, [1.0, 1.99, 2.0]) == 0  # at the limit is within it
    assert _count(monkeypatch, [2.0, 2.0000001, 2.5, 1.5]) == 2  # both sides of the limit


def test_a_nan_pue_counts_as_a_violation_like_the_envelope(monkeypatch):
    assert _count(monkeypatch, [1.2, math.nan, 1.2]) == 1
    assert "pue_above_max" in SAFETY_ENVELOPE.violations(22.0, 35.0, math.nan)


@pytest.mark.parametrize("pue", [1.0, 1.999, 2.0, 2.001, 3.0, math.nan, math.inf])
def test_the_counter_agrees_with_the_safety_envelope_on_every_value(monkeypatch, pue):
    assert bool(_count(monkeypatch, [pue])) == ("pue_above_max" in SAFETY_ENVELOPE.violations(22.0, 35.0, pue))


def test_the_metric_is_registered_and_a_hard_constraint():
    assert PUE in pe.METRICS and pe.METRICS[PUE][0] == "lower"
    assert PUE in pe.HARD_CONSTRAINT_METRICS and len(pe.HARD_CONSTRAINT_METRICS) == 4
    assert PUE in tuning._ENVELOPE_METRICS and "pue_over_max_steps" in tuning.FEASIBILITY_RULE


def test_a_real_episode_reports_the_metric_and_it_is_zero_for_a_sane_controller():
    cfg = pe.EvalConfig(episode_steps=24)
    sc = pe.build_scenarios(pe.EvalConfig(n_test_per_family=1))["test"][0]
    m = pe.run_episode(pe.RulePolicy(cfg.rule_chilled_C, physics_version="1"), sc, cfg, np.full(24, 475.0)).metrics
    assert m[PUE] == 0.0 and m["mean_pue"] < PUE_MAX_SAFE


# --------------------------------------------------------------------------------------- decision rules
def test_a_pue_only_violation_by_the_candidate_blocks_outcome_A_and_gives_B():
    d = _decide(-40.0, -150.0, -58.0, ppo_over={PUE: 1.0})  # clearly better than both, safe on the other three
    assert d["outcome"] == "B" and d["claim_allowed"] == "none"
    env = d["detail"]["envelope_selected_candidate"]
    assert env["ok"] is False and env[PUE] > 0 and env["outlet_violation_steps"] == 0


def test_the_same_candidate_without_the_pue_violation_is_outcome_A():
    assert _decide(-40.0, -150.0, -58.0)["outcome"] == "A"


def test_a_baseline_that_violates_pue_cannot_be_the_replacement_controller():
    d = _decide(-60.0, -150.0, -58.0, const_over={PUE: 1.0})
    assert d["outcome"] == "B" and d["simpler_controllers_within_tolerance"] == []
    assert d["detail"]["per_baseline"]["best_constant"]["baseline_envelope_safe"] is False


def test_the_outcome_rules_and_prereg_document_state_amendment_a2():
    assert "PUE-over-limit" in pe.OUTCOME_RULES["A"] and "A2" in pe.OUTCOME_RULES["A"]
    assert "PUE-over-limit" in pe.OUTCOME_RULES["C"] and "A2" in pe.OUTCOME_RULES["C"]
    doc = pe.preregistration_document(pe.EvalConfig(n_validation_per_family=1, n_test_per_family=1))
    assert doc["schema_version"] == pe.SCHEMA_VERSION == 2 and PUE in doc["metrics"]


def test_a_small_baselines_only_run_writes_schema_2_with_the_metric_everywhere():
    from dataclasses import replace

    cfg = replace(pe.EvalConfig(), n_validation_per_family=1, n_test_per_family=1, episode_steps=12)
    res = pe.run_evaluation(cfg, ppo_candidates=None, carbon_curve=np.full(24, 475.0), carbon_is_real=False)
    assert res["schema_version"] == 2
    for policy, row in res["summary_test_mean_per_episode"].items():
        assert row[PUE] == 0.0, policy
        assert pe.pue_limit_measured(row)
    assert all(PUE in r for rows in res["per_scenario_test"].values() for r in rows)
    assert PUE in pe.results_markdown(res)


# --------------------------------------------------------------------------------------- old results still load
def test_the_frozen_legacy_report_is_unchanged_and_is_schema_1_without_the_key():
    raw = LEGACY_RESULTS.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LEGACY_RESULTS_SHA256
    res = json.loads(raw)
    assert res["schema_version"] == 1
    assert all(not pe.pue_limit_measured(v) for v in res["summary_test_mean_per_episode"].values())
    assert 1 in pe.SUPPORTED_RESULT_SCHEMAS and pe.SCHEMA_VERSION in pe.SUPPORTED_RESULT_SCHEMAS


def test_api_hard_constraint_list_matches_the_harness():
    from api.services import evaluation_service as ES

    assert ES._HARD_CONSTRAINTS == pe.HARD_CONSTRAINT_METRICS


@pytest.fixture
def reports(tmp_path, monkeypatch):
    from api.services import evaluation_service as ES

    dst = tmp_path / "policy_evaluation"
    shutil.copytree(ROOT / "reports" / "policy_evaluation", dst)
    monkeypatch.setattr(ES, "reports_dir", lambda: dst)
    return dst


def test_the_api_serves_a_schema_1_report_and_says_the_pue_limit_was_not_measured(reports):
    from api.services import evaluation_service as ES

    d = ES.get_evaluation("baselines_only_0fcafef9d28fd539")
    assert d["schema_version"] == 1
    hc = d["hard_constraints"]
    assert hc["not_measured"] == [PUE] and PUE not in hc["counted"] and len(hc["counted"]) == 3
    assert "not the same as zero" in hc["note"]
    assert all(PUE not in p["metrics"] for p in d["policies"])  # nothing invented: no zero filled in


def test_the_api_serves_a_schema_2_report_with_all_four_limits_counted(reports):
    from api.services import evaluation_service as ES

    raw = json.loads((reports / "baselines_only_0fcafef9d28fd539" / "results.json").read_text(encoding="utf-8"))
    new = copy.deepcopy(raw)
    new["schema_version"] = 2
    for v in new["summary_test_mean_per_episode"].values():
        v[PUE] = 0.0
    for rows in new["per_scenario_test"].values():
        for r in rows:
            r[PUE] = 0.0
    (reports / "v2_report").mkdir()
    (reports / "v2_report" / "results.json").write_text(json.dumps(new), encoding="utf-8")
    d = ES.get_evaluation("v2_report")
    assert d["schema_version"] == 2 and d["hard_constraints"] == {
        "counted": list(pe.HARD_CONSTRAINT_METRICS), "not_measured": [], "note": None,
    }  # fmt: skip
    assert {i["evaluation_id"] for i in ES.list_evaluations()["evaluations"]} >= {"v2_report"}


def test_a_report_with_an_unknown_schema_is_still_refused(reports):
    from api.services import evaluation_service as ES

    raw = json.loads((reports / "baselines_only_0fcafef9d28fd539" / "results.json").read_text(encoding="utf-8"))
    raw["schema_version"] = 3
    (reports / "v3_report").mkdir()
    (reports / "v3_report" / "results.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Exception) as exc:
        ES.get_evaluation("v3_report")
    assert getattr(exc.value, "status_code", None) == 404


# --------------------------------------------------------------------------------------- baselines must be re-tuned
def test_a_baseline_config_tuned_under_the_old_feasibility_rule_is_refused_by_the_run():
    prereg = ROOT / "reports" / "policy_evaluation_physics1"
    eval_cfg = pe.load_preregistered_config(prereg)
    val = pe.build_scenarios(eval_cfg)["validation"]
    paths = {n: f"configs/baselines/{n}.json" for n in bcfg.BASELINE_NAMES}
    cfg = bcfg.load_config(ROOT / paths["rule"], "rule")
    if cfg["tuning"]["feasibility_rule"] == tuning.FEASIBILITY_RULE:
        pytest.skip("the shipped configs were already re-tuned under amendment A2")
    with pytest.raises(bcfg.BaselineConfigStale) as exc:
        bev.load_baselines(ROOT, paths, eval_cfg, val, "x")
    assert exc.value.field == "tuning.feasibility_rule"
