"""Task 5 (ENG-001): ONE hard-constraint set (outlet, inlet-over, inlet-under, PUE) for tuner, harness, recommendation.

Hermetic: the plant is a stub environment and every config is a tmp copy of the shipped one; nothing under configs/ or
reports/ is read for its numbers or written. Before the fix the tuner's own set omitted PUE, so a candidate the harness
counts as an envelope violation could be tuned as "feasible", stored as the baseline, and recommended.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from src import baseline_recommendation as br
from src import policy_evaluation as pe
from src import run_export
from src.baselines import config as bc
from src.baselines import tuning
from src.baselines.policies import actuator_range_C
from src.rl.env import UnsupportedPhysicsVersionForRL
from src.versions import LEGACY_PHYSICS_VERSION, PHYSICS_V1

ROOT = Path(__file__).resolve().parents[1]
PUE = "pue_over_max_steps"
CARBON = np.full(24, 475.0)


# ----------------------------------------------------------------------------- stub plant


class _PueByActionEnv:
    """Reward rises with the (normalised) set-point and PUE exceeds its limit above 0.5: the shape of the real trade-off
    (the reward prefers warm water), with the PUE limit the ONLY constraint that is ever violated."""

    def __init__(self, **kw):
        self.physics_version = kw["physics_version"]

    @staticmethod
    def _state(pue: float) -> dict:
        return {
            "hour": 0.0, "utilisation": 0.5, "outside_temp": 20.0, "water_stress": 0.0, "it_power": 100.0,
            "cooling_power": 10.0, "water_consumed": 1.0, "carbon_gco2": 1.0, "pue": pue, "wue": 0.5,
            "outlet_temp": 35.0, "inlet_temp": 22.0,
        }  # fmt: skip

    def reset(self, seed=None):
        return np.zeros(3), {}

    def get_state_dict(self):
        return self._state(1.2)

    def step(self, action):
        norm = float(action[0])
        return np.zeros(3), norm, False, False, {"state": self._state(2.5 if norm > 0.5 else 1.2)}

    def close(self):
        pass


def _cfg(physics: str) -> pe.EvalConfig:
    if physics == LEGACY_PHYSICS_VERSION:  # a legacy-0 protocol carries its own explicit 5..15 C values
        return pe.EvalConfig(
            physics_version=physics,
            episode_steps=6,
            constant_chilled_C=pe.constant_grid_c(physics),
            rule_chilled_C=12.0,
        )
    return pe.EvalConfig(physics_version=physics, episode_steps=6)


def _validation(cfg: pe.EvalConfig):
    return pe.build_scenarios(pe.EvalConfig(n_validation_per_family=1, n_test_per_family=1))["validation"][:1]


# ----------------------------------------------------------------------------- one definition


def test_the_tuner_uses_the_harnesss_constraint_set_not_a_copy():
    assert tuning._ENVELOPE_METRICS == pe.HARD_CONSTRAINT_METRICS and PUE in tuning._ENVELOPE_METRICS
    assert run_export.HARD_CONSTRAINT_METRICS == pe.HARD_CONSTRAINT_METRICS  # the export's own copy cannot drift
    for metric in pe.HARD_CONSTRAINT_METRICS:
        assert metric in tuning.FEASIBILITY_RULE  # the recorded rule names every counted constraint


def test_feasibility_needs_every_hard_constraint_counted_and_zero():
    zero = {m: 0 for m in pe.HARD_CONSTRAINT_METRICS}
    assert tuning.is_feasible(zero) is True
    for metric in pe.HARD_CONSTRAINT_METRICS:
        assert tuning.is_feasible({**zero, metric: 1}) is False, metric
    only_temperatures = {k: v for k, v in zero.items() if k != PUE}  # the old three-key shape
    with pytest.raises(ValueError):  # a missing count is an error, never a silent zero
        tuning.is_feasible(only_temperatures)


@pytest.mark.parametrize(
    "pue, violates",
    [(1.2, False), (pe.PUE_MAX_SAFE, False), (pe.PUE_MAX_SAFE + 1e-6, True), (math.inf, True), (math.nan, True)],
)
def test_a_step_is_judged_against_the_same_pue_limit_as_the_harness(pue, violates):
    state = {"outlet_temp": 35.0, "inlet_temp": 22.0, "pue": pue}
    assert tuning.step_violates_envelope(state) is violates


def test_a_step_over_any_other_limit_is_still_a_violation():
    base = {"outlet_temp": 35.0, "inlet_temp": 22.0, "pue": 1.2}
    assert tuning.step_violates_envelope(base) is False
    assert tuning.step_violates_envelope({**base, "outlet_temp": pe.OUTLET_MAX + 0.1}) is True
    assert tuning.step_violates_envelope({**base, "inlet_temp": pe.INLET_TEMP_MAX + 0.1}) is True
    assert tuning.step_violates_envelope({**base, "inlet_temp": pe.INLET_TEMP_MIN - 0.1}) is True


# ----------------------------------------------------------------------------- the tuner, on both physics versions


@pytest.mark.parametrize("physics", [LEGACY_PHYSICS_VERSION, PHYSICS_V1])
def test_a_candidate_with_pue_over_max_steps_is_never_feasible_and_never_selected(monkeypatch, physics):
    monkeypatch.setattr(pe, "DataCentreEnv", _PueByActionEnv)
    cfg = _cfg(physics)
    sweep = tuning.ActionSweep(_validation(cfg), cfg, CARBON)
    lo, hi = actuator_range_C(physics)
    space = tuning.default_space(cfg)
    res = tuning.tune_constant(space, sweep)
    cands = res["result"]["candidates"]
    over = [c for c in cands if c["violation_steps"][PUE] > 0]
    assert over and all(not c["feasible"] for c in over)  # both the set-points above mid-range violate PUE
    assert all(c["violation_steps"]["outlet_violation_steps"] == 0 for c in cands)  # PUE is the ONLY violation here
    # the violating set-points earn the HIGHEST reward (reward rises with the set-point), so an envelope that
    # forgot PUE would select the top of the range: the selection must stop at the last PUE-feasible one.
    assert max(c["validation_reward"] for c in cands) == max(c["validation_reward"] for c in over)
    assert res["status"] == "feasible"
    # normalised 0.5 is the last set-point at or below the stub's PUE limit
    assert res["parameters"]["selected"]["chilled_C"] == pytest.approx(lo + 0.5 * (hi - lo))


@pytest.mark.parametrize("physics", [LEGACY_PHYSICS_VERSION, PHYSICS_V1])
def test_the_rule_that_violates_pue_is_recorded_infeasible(monkeypatch, physics):
    cfg = _cfg(physics)

    def over_limit(policy, scenarios, eval_cfg, carbon):
        monkeypatch.setattr(pe, "DataCentreEnv", _PueByActionEnv)
        policy = type("Hot", (), {"act": lambda self, obs, state: np.array([1.0, 0.0], dtype=np.float32)})()
        return [pe.run_episode(policy, s, eval_cfg, carbon) for s in scenarios]

    monkeypatch.setattr(pe, "evaluate_policy", over_limit)
    out = tuning.tune_rule(tuning.default_space(cfg), _validation(cfg), cfg, CARBON)
    assert out["status"] == "infeasible" and PUE in out["reason"]
    assert out["result"]["validation_violation_steps"][PUE] > 0


@pytest.mark.parametrize("physics", [LEGACY_PHYSICS_VERSION, PHYSICS_V1])
def test_lookup_cells_count_pue_violations(monkeypatch, physics):
    monkeypatch.setattr(pe, "DataCentreEnv", _PueByActionEnv)
    cfg = _cfg(physics)
    sweep = tuning.ActionSweep(_validation(cfg), cfg, CARBON)
    lo, hi = actuator_range_C(physics)
    _, hot = sweep.get(hi, "closed_loop")
    _, cool = sweep.get(lo, "closed_loop")
    assert hot[..., 3].min() == 1.0 and cool[..., 3].max() == 0.0  # the per-step flag Lookup attributes to bins


# ----------------------------------------------------------------------------- the recommendation


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
    args = {"outside_temp": 22.0, "water_stress": 0.0, "current_chilled_c": 20.0, "inlet_temp_c": None}
    return br.recommend(root, **{**args, **kw})


def _retuned_under_the_current_rule(cfg: dict) -> None:
    """What a re-tune records: today's rule text and a (zero) count for EVERY hard constraint."""
    cfg["tuning"]["feasibility_rule"] = tuning.FEASIBILITY_RULE
    result = cfg["tuning"]["result"]
    zero = {m: 0 for m in pe.HARD_CONSTRAINT_METRICS}
    if cfg["name"] == "rule":
        result["validation_violation_steps"] = zero
    else:
        for cand in result["candidates"]:
            cand["violation_steps"] = dict(zero)


_OLD_RULE = "zero outlet_violation_steps, inlet_over_max_steps and inlet_under_min_steps in every validation episode"


def _tuned_before_pue_was_counted(cfg: dict) -> None:
    """What the configs shipped before Task 17 looked like: the three-metric rule text and no stored PUE count."""
    cfg["tuning"]["feasibility_rule"] = _OLD_RULE
    result = cfg["tuning"]["result"]
    if cfg["name"] == "rule":
        result["validation_violation_steps"].pop(PUE, None)
    else:
        for cand in result["candidates"]:
            cand["violation_steps"].pop(PUE, None)


def test_the_shipped_configs_were_tuned_under_the_current_rule_with_every_hard_constraint_counted(configs):
    # Task 17 (ML-002): the re-tune records today's rule and a stored count for all four hard constraints, none violated.
    for name in ("constant", "lookup", "pid", "rule"):
        cfg = bc.load_config(bc.config_path(name, configs), name)
        assert cfg["tuner_version"] == tuning.TUNER_VERSION, name
        assert cfg["tuning"]["feasibility_rule"] == tuning.FEASIBILITY_RULE, name
    for name in ("rule", "pid"):
        assert br.hard_constraint_status(bc.load_config(bc.config_path(name, configs), name)) == ([], []), name
    lineage = _rec(configs)["selected"]["lineage"]
    assert lineage["feasibility_rule_is_current"] is True and lineage["hard_constraints_not_counted"] == []


def test_a_config_with_stored_pue_violations_is_never_recommended(configs):
    for name in ("rule", "pid"):
        _edit(configs, name, _retuned_under_the_current_rule)
    assert _rec(configs)["selected"] is not None  # control: zero counts everywhere -> usable

    def violate_rule(cfg):
        cfg["tuning"]["result"]["validation_violation_steps"][PUE] = 3  # status still says "feasible"

    _edit(configs, "rule", violate_rule)
    rec = _rec(configs)
    rule = next(c for c in rec["considered"] if c["name"] == "rule")
    assert rule["usable"] is False and PUE in rule["reason"]
    assert rec["selected"]["name"] == "pid"  # the other one is still fine

    def violate_pid(cfg):  # the counts of the candidate THIS config selected
        for cand in cfg["tuning"]["result"]["candidates"]:
            cand["violation_steps"][PUE] = 1

    _edit(configs, "pid", violate_pid)
    rec = _rec(configs)
    assert rec["selected"] is None and all(not c["usable"] for c in rec["considered"])


def test_hard_constraint_status_separates_violated_from_not_counted(configs):
    cfg = bc.load_config(bc.config_path("rule", configs), "rule")
    assert br.hard_constraint_status(cfg) == (
        [],
        [],
    )  # shipped (Task 17 re-tune): every constraint counted, none violated
    _tuned_before_pue_was_counted(cfg)
    assert br.hard_constraint_status(cfg) == ([], [PUE])  # an older config: PUE NOT MEASURED, which is not a zero
    _retuned_under_the_current_rule(cfg)
    assert br.hard_constraint_status(cfg) == ([], [])
    cfg["tuning"]["result"]["validation_violation_steps"]["inlet_under_min_steps"] = 2
    cfg["tuning"]["result"]["validation_violation_steps"][PUE] = math.nan  # NaN is a violation, not a zero
    assert br.hard_constraint_status(cfg) == (["inlet_under_min_steps", PUE], [])


def test_the_recommendation_carries_config_lineage_and_flags_an_old_feasibility_rule(configs):
    for name in ("rule", "pid"):
        _edit(configs, name, _tuned_before_pue_was_counted)
    sel = _rec(configs)["selected"]
    lineage = sel["lineage"]
    assert lineage["physics_version"] == sel["physics_version"] and lineage["tuner_version"] == sel["tuner_version"]
    assert set(bc.LINEAGE_FIELDS) <= set(lineage)
    assert len(lineage["config_sha256"]) == 64
    assert lineage["hard_constraints"] == list(pe.HARD_CONSTRAINT_METRICS)
    # a config that predates the PUE constraint: say so instead of implying PUE was checked
    assert lineage["feasibility_rule_is_current"] is False and lineage["hard_constraints_not_counted"] == [PUE]
    assert sel["caveats"] and "re-tune" in sel["caveats"][0]

    for name in ("rule", "pid"):
        _edit(configs, name, _retuned_under_the_current_rule)
    sel = _rec(configs)["selected"]
    lineage = sel["lineage"]
    assert lineage["feasibility_rule_is_current"] is True and lineage["hard_constraints_not_counted"] == []
    assert sel["caveats"] == [] and lineage["feasibility_rule"] == tuning.FEASIBILITY_RULE


# ----------------------------------------------------------------------------- unsupported physics raises, never clips


@pytest.mark.parametrize("physics, lo, hi", [(LEGACY_PHYSICS_VERSION, 5.0, 15.0), (PHYSICS_V1, 16.0, 25.0)])
def test_the_set_point_scale_is_the_physics_own_on_both_supported_versions(physics, lo, hi):
    assert actuator_range_C(physics) == (lo, hi)
    assert br._denormalise(np.array([0.0, 0.0]), physics)[0] == lo
    assert br._denormalise(np.array([1.0, 0.0]), physics)[0] == hi
    assert br._denormalise(np.array([0.5, 0.0]), physics)[0] == pytest.approx((lo + hi) / 2)


@pytest.mark.parametrize("physics", ["2", "999", ""])
def test_an_unsupported_physics_version_raises_instead_of_clipping(physics):
    with pytest.raises(UnsupportedPhysicsVersionForRL):
        br._denormalise(np.array([0.5, 0.0]), physics)
    with pytest.raises(UnsupportedPhysicsVersionForRL):
        br._to_policy_scale(20.0, physics, PHYSICS_V1)


def test_a_config_on_an_unsupported_physics_is_skipped_with_an_accurate_reason(configs, monkeypatch):
    for name in ("pid", "rule"):
        _edit(configs, name, _retuned_under_the_current_rule)

    def refuse(cfg):
        raise UnsupportedPhysicsVersionForRL("physics version '2' is not supported by the RL environment")

    monkeypatch.setattr(bc, "build_policy", refuse)
    rec = _rec(configs)
    assert rec["selected"] is None
    assert all("not supported by the RL environment" in c["reason"] for c in rec["considered"])
