"""Task 19: approval rules, predicted-effect arithmetic and the baseline recommendation (no database, no network)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src import baseline_recommendation as br
from src import optimizer_proposals as rules
from src.baselines import config as bc

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
    # Task 5 (ENG-001): the rewards are set HERE. The shipped physics-1 configs are re-tuned whenever the protocol
    # changes and currently TIE (the tuned PID's best gains are zero, i.e. the rule), so the shipped numbers cannot
    # pin "the higher stored reward wins". The old expectation (-91.05 vs -92.16) was the legacy-0 tuning.
    _edit(configs, "pid", lambda c: c["tuning"]["result"].update(validation_reward=-91.05))
    _edit(configs, "rule", lambda c: c["tuning"]["result"].update(validation_reward=-92.16))
    rec = _rec(configs)
    assert [c["name"] for c in rec["considered"]] == ["pid", "rule"] and all(c["usable"] for c in rec["considered"])
    assert rec["selected"]["name"] == "pid"
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
    # Task 5 (ENG-001): a physics-1 config stores its set-point in physics-1 degrees (16..25 C), so the recommendation
    # is that value exactly. (Until Task 3 the stored 12.0 was a legacy 5..15 C position, reported as 22.3 C; the
    # shipped config is now physics-1-native, 20.5 C, and a legacy value is rejected by the policy, not rescaled.)
    _edit(configs, "rule", lambda c: c["parameters"].update(chilled_C=22.0))
    hot = _rec(configs, outside_temp=35.0)["selected"]
    assert hot["name"] == "rule" and hot["chilled_water_temp_C"] == pytest.approx(22.0, abs=1e-3)
    drought = _rec(configs, outside_temp=5.0, water_stress=0.9)["selected"]
    assert drought["cooling_mode"] == "closed_loop"  # the drought override wins even on a cold day


def _pid_only(configs, **gains):
    """Only the PID is usable, with explicit physics-1 gains (the shipped tuned PID has kp = ki = kd = 0)."""
    _edit(configs, "rule", lambda c: c.update(status="infeasible", infeasible_reason="x"))
    _edit(configs, "pid", lambda c: c["parameters"].update(selected_gains={"kp": 1.0, "ki": 0.0, "kd": 0.0, **gains}))


def test_pid_without_an_inlet_reports_its_nominal_set_point_and_says_so(configs):
    # the config's own nominal set-point (physics 1: 20.5 C, the middle of 16..25), not legacy-0's 12 C
    _pid_only(configs)  # the shipped PID and rule currently tie on reward and a tie goes to the rule
    nominal = bc.load_config(bc.config_path("pid", configs), "pid")["parameters"]["nominal_setpoint_C"]
    sel = _rec(configs)["selected"]
    assert sel["name"] == "pid" and sel["chilled_water_temp_C"] == pytest.approx(nominal)
    assert "nominal" in sel["basis"]


def test_pid_with_an_inlet_takes_one_rate_limited_step_from_the_current_setpoint(configs):
    # Task 5 (ENG-001): the same law on the physics-1 scale. u = nominal(20.5) + kp(1) * (target(22) - inlet), the step
    # is limited to +-2 C (stored max_rate) around the CURRENT set-point and to the actuator range 16..25 C.
    _pid_only(configs)
    sel = _rec(configs, inlet_temp_c=21.0, current_chilled_c=21.0)["selected"]  # 1 C too cold: 20.5 + 1
    assert sel["chilled_water_temp_C"] == pytest.approx(21.5)
    assert "one PID step" in sel["basis"]
    # a 6 C error asks for 26.5 but the controller moves at most the stored rate per step (2 C) from 18 C
    far = _rec(configs, inlet_temp_c=16.0, current_chilled_c=18.0)["selected"]
    assert far["chilled_water_temp_C"] == pytest.approx(20.0)
    # and never outside the actuator range
    assert 16.0 <= _rec(configs, inlet_temp_c=40.0, current_chilled_c=16.5)["selected"]["chilled_water_temp_C"] <= 25.0


def test_same_inputs_same_recommendation(configs):
    assert _rec(configs, inlet_temp_c=21.0) == _rec(configs, inlet_temp_c=21.0)


def test_the_api_mode_vocabulary_is_the_optimizers():
    from typing import get_args

    from api.plugins import optimizer_proposals as plugin
    from src.optimizer import COOLING_MODES

    assert set(get_args(plugin.Mode)) == set(COOLING_MODES)
    assert set(get_args(plugin.CurrentMode)) == set(COOLING_MODES) | {"auto"}
