"""Task 19: approval rules, predicted-effect arithmetic and the baseline recommendation (no database, no network)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src import baseline_recommendation as br
from src import optimizer_proposals as rules

ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- approval rules


def test_only_a_pending_proposal_can_be_decided():
    rules.check_decision("pending", "op1", "admin1")
    for status in ("approved", "rejected"):
        with pytest.raises(rules.DecisionError) as exc:
            rules.check_decision(status, "op1", "admin1")
        assert exc.value.code == "not_pending"


def test_nobody_decides_their_own_proposal():
    with pytest.raises(rules.DecisionError) as exc:
        rules.check_decision("pending", "admin1", "admin1")
    assert exc.value.code == "self_decision"


def test_role_gates():
    roles = ("viewer", "operator", "admin", None, "root")
    assert [rules.can_propose(r) for r in roles] == [False, True, True, False, False]
    assert [rules.can_decide(r) for r in roles] == [False, False, True, False, False]


def test_decisions_map_to_statuses():
    assert rules.DECISIONS == {"approve": "approved", "reject": "rejected"}


# ----------------------------------------------------------------------------- predicted effect


def _run(pue, energy, co2, outlet, real=True):
    return {
        "hours": 24,
        "mean_pue": pue,
        "total_energy_kwh": energy,
        "total_co2_kg": co2,
        "max_outlet_temp_C": outlet,
        "carbon_data_is_real": real,
    }


def test_predicted_effect_golden_numbers():
    e = rules.predicted_effect(_run(1.5, 1000.0, 400.0, 30.0), _run(1.4, 900.0, 360.0, 33.0), 35.0)
    assert e["label"] == "model estimate on simulated data"
    expected = {
        "mean_pue": -0.1,
        "total_energy_kwh": -100.0,
        "total_co2_kg": -40.0,
        "max_outlet_temp_C": 3.0,
        "thermal_margin_C": -3.0,
    }
    assert e["delta"] == pytest.approx(expected)
    assert e["reference"]["thermal_margin_C"] == 5.0 and e["proposed"]["thermal_margin_C"] == 2.0
    assert e["within_outlet_limit"] is True and e["outlet_limit_C"] == 35.0 and e["hours"] == 24


def test_a_run_over_the_outlet_limit_is_flagged():
    e = rules.predicted_effect(_run(1.5, 1000.0, 400.0, 30.0), _run(1.3, 800.0, 300.0, 36.0), 35.0)
    assert e["within_outlet_limit"] is False and e["proposed"]["thermal_margin_C"] == -1.0


def test_carbon_is_real_only_when_both_runs_used_a_real_series():
    base = _run(1.5, 1000.0, 400.0, 30.0)
    assert rules.predicted_effect(base, _run(1.4, 900.0, 360.0, 31.0), 35.0)["carbon_data_is_real"] is True
    assert rules.predicted_effect(base, _run(1.4, 900.0, 360.0, 31.0, real=False), 35.0)["carbon_data_is_real"] is False


def test_labels_do_not_overclaim():
    assert "does not apply" in rules.APPROVAL_LABEL
    assert "measured" not in rules.PREDICTION_LABEL and "optimal" not in rules.PREDICTION_LABEL


# ----------------------------------------------------------------------------- baseline recommendation


@pytest.fixture
def configs(tmp_path):
    shutil.copytree(ROOT / "configs" / "baselines", tmp_path / "configs" / "baselines")
    return tmp_path


def _edit(root: Path, name: str, fn) -> None:
    path = root / "configs" / "baselines" / f"{name}.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    fn(cfg)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def _rec(root, **kw):
    args = {"outside_temp": 22.0, "water_stress": 0.0, "current_chilled_c": 10.0, "inlet_temp_c": None}
    return br.recommend(root, **{**args, **kw})


def test_the_stored_validation_reward_decides_between_pid_and_rule(configs):
    rec = _rec(configs)
    assert [c["name"] for c in rec["considered"]] == ["pid", "rule"] and all(c["usable"] for c in rec["considered"])
    assert rec["selected"]["name"] == "pid"  # -91.05 beats the rule's -92.16 in the shipped configs
    _edit(configs, "rule", lambda c: c["tuning"]["result"].update(validation_reward=-50.0))
    assert _rec(configs)["selected"]["name"] == "rule"
    assert "not an evaluation" in rec["note"] and "PPO" in rec["note"]


def test_an_exact_tie_goes_to_the_rule(configs):
    reward = -80.0
    _edit(configs, "rule", lambda c: c["tuning"]["result"].update(validation_reward=reward))
    _edit(configs, "pid", lambda c: c["tuning"]["result"]["least_violating"].update(validation_reward=reward))
    _edit(configs, "pid", lambda c: c["tuning"]["result"].update(validation_reward=reward))
    assert _rec(configs)["selected"]["name"] == "rule"


def test_an_infeasible_stale_or_missing_config_is_skipped_with_a_reason(configs):
    def infeasible(c):
        c["status"] = "infeasible"
        c["infeasible_reason"] = "no candidate met the envelope"

    _edit(configs, "pid", infeasible)
    rec = _rec(configs)
    pid = next(c for c in rec["considered"] if c["name"] == "pid")
    assert pid["usable"] is False and "infeasible" in pid["reason"] and rec["selected"]["name"] == "rule"

    _edit(configs, "rule", lambda c: c["lineage"].update(physics_version="999"))
    rec = _rec(configs)
    assert rec["selected"] is None
    assert "re-tune" in next(c for c in rec["considered"] if c["name"] == "rule")["reason"]

    (configs / "configs" / "baselines" / "rule.json").unlink()
    assert "missing or malformed" in next(c for c in _rec(configs)["considered"] if c["name"] == "rule")["reason"]


def test_rule_setpoints_are_the_stored_chilled_c_and_the_production_mode(configs):
    _edit(configs, "pid", lambda c: c.update(status="infeasible", infeasible_reason="x"))
    hot = _rec(configs, outside_temp=35.0)["selected"]
    # Task 3: the stored 12.0 is a position on the legacy 5..15 C scale (0.7). The evaluation executed that action at
    # lo + 0.7 * (hi - lo) of the RUNNING physics' actuator range (22.3 C under physics 1), and so is reported.
    from src.baselines.policies import actuator_range_C
    from src.versions import active_physics_version

    lo, hi = actuator_range_C(active_physics_version())
    assert hot["name"] == "rule" and hot["chilled_water_temp_C"] == pytest.approx(lo + 0.7 * (hi - lo), abs=1e-3)
    drought = _rec(configs, outside_temp=5.0, water_stress=0.9)["selected"]
    assert drought["cooling_mode"] == "closed_loop"  # the drought override wins even on a cold day


def test_pid_without_an_inlet_reports_its_nominal_set_point_and_says_so(configs):
    sel = _rec(configs)["selected"]
    assert sel["name"] == "pid" and sel["chilled_water_temp_C"] == 12.0
    assert "nominal" in sel["basis"]


def test_pid_with_an_inlet_takes_one_rate_limited_step_from_the_current_setpoint(configs):
    # kp = 1, target inlet 22 C: an inlet of 20 C is 2 C too cold -> set-point up by 2 from the current 8 C
    sel = _rec(configs, inlet_temp_c=20.0, current_chilled_c=8.0)["selected"]
    assert sel["chilled_water_temp_C"] == pytest.approx(10.0)
    assert "one PID step" in sel["basis"]
    # a 6 C error asks for +6 but the controller moves at most the stored rate per step (2 C)
    far = _rec(configs, inlet_temp_c=16.0, current_chilled_c=8.0)["selected"]
    assert far["chilled_water_temp_C"] == pytest.approx(10.0)
    # and never outside the actuator range
    assert 5.0 <= _rec(configs, inlet_temp_c=40.0, current_chilled_c=5.5)["selected"]["chilled_water_temp_C"] <= 15.0


def test_same_inputs_same_recommendation(configs):
    assert _rec(configs, inlet_temp_c=21.0) == _rec(configs, inlet_temp_c=21.0)


def test_the_api_mode_vocabulary_is_the_optimizers():
    from typing import get_args

    from api.plugins import optimizer_proposals as plugin
    from src.optimizer import COOLING_MODES

    assert set(get_args(plugin.Mode)) == set(COOLING_MODES)
    assert set(get_args(plugin.CurrentMode)) == set(COOLING_MODES) | {"auto"}
