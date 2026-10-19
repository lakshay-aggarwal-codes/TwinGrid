"""Task 20 (roadmap): the documents agree with the code and with the results actually obtained.

No network, no training. The physics-1 decision run is read from the committed ``results.json``; if the run directory is
absent the result-dependent tests skip with a clear message (they never pass on a missing file).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "reports" / "policy_evaluation_physics1" / "full_0fcafef9d28fd539"
CARD = ROOT / "docs" / "model_cards" / "ppo_optimizer.md"
SCAN_DIRS = ("src", "api")


def _results() -> dict:
    p = RUN / "results.json"
    if not p.exists():
        pytest.skip(f"{p} not present: commit the Task 9 run before relying on this test")
    return json.loads(p.read_text(encoding="utf-8"))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_patent_wording_in_source_except_the_compatibility_key():
    hits = []
    for d in SCAN_DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix not in {".py", ".md", ".ts", ".yaml", ".yml", ".json"} or "__pycache__" in p.parts:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if re.search(r"patent", line, re.I) and '"patent_objective"' not in line:
                    hits.append(f"{p.relative_to(ROOT)}:{n}")
    assert hits == [], hits


def test_patent_objective_key_is_kept_only_as_a_documented_label():
    src = _read("src/optimizer.py")
    assert '"patent_objective"' in src and "kept for compatibility" in src
    assert "kept for compatibility" in _read("config.yaml")


def test_rl_env_comments_do_not_state_the_legacy_setpoint_range_as_current():
    env = _read("src/rl/env.py")
    assert "Action = [chilled_water_temp 5–15°C" not in env
    assert "CHILLED_WATER_ACTION_RANGE_C" in env


def test_readme_has_a_limitations_section_with_the_four_required_limits():
    readme = _read("README.md")
    m = re.search(r"^## Limitations\n(.*?)(?=^## )", readme, re.S | re.M)
    assert m, "README has no '## Limitations' section"
    body = m.group(1).lower()
    for needle in ("simulated", "lumped", "assumed carbon", "no calibration"):
        assert needle in body, needle


def test_card_and_ledger_state_the_obtained_decision_outcome():
    res = _results()
    outcome = res["decision"]["outcome"]
    assert outcome in {"A", "B", "C"}
    card, claims = CARD.read_text(encoding="utf-8"), _read("docs/CLAIMS.md")
    assert f"Outcome `{outcome}`" in card
    row = next(ln for ln in claims.splitlines() if ln.startswith("| C-08 |"))
    assert f"outcome is `{outcome}`" in row
    assert str(res["decision"]["claim_allowed"]) in row


def test_docs_do_not_claim_a_ppo_win_or_unevaluated_candidates_when_outcome_is_c():
    res = _results()
    if res["decision"]["outcome"] != "C":
        pytest.skip("only meaningful for outcome C")
    for rel in (
        "README.md",
        "docs/CLAIMS.md",
        "docs/JUDGES.md",
        "docs/model_cards/LIMITATIONS.md",
        "ML_DOCUMENTATION.md",
    ):
        low = " ".join(_read(rel).lower().split())
        assert "newer candidates are not evaluated" not in low, rel
        assert "trained, not evaluated, not promoted" not in low, rel
        assert "ppo beats" not in low and "outperforms the rule" not in low, rel


def test_card_statements_match_the_run_numbers():
    res = _results()
    summ = res["summary_test_mean_per_episode"]
    seeds = [k for k in summ if k.startswith("ppo_seed_")]
    assert len(seeds) == 5
    best = summ["best_constant"]["total_reward"]
    # "scored higher than every PPO seed" and "used far less water than every PPO seed and the rule baseline"
    assert all(best > summ[s]["total_reward"] for s in seeds)
    assert all(summ["best_constant"]["water_L"] < summ[k]["water_L"] / 2 for k in seeds + ["rule"])
    # "zero outlet-over-limit, inlet-over-max, inlet-under-min and PUE-over-limit steps"
    for k in seeds + ["rule", "best_constant"]:
        for m in ("outlet_violation_steps", "inlet_over_max_steps", "inlet_under_min_steps", "pue_over_max_steps"):
            assert summ[k][m] == 0, (k, m)
    # "the selected seed scored higher than the rule baseline across the 60 test scenarios (interval excludes zero)"
    sel = f"ppo_seed_{res['selection']['selected_ppo_seed']}"
    per = res["decision"]["detail"]["per_baseline"]
    assert per["rule"]["scenario_level_diff"]["ci_low"] > 0
    assert per["rule"]["criteria"]["advantage_positive_in_every_family"] is False
    assert per["rule"]["seed_level_diff"]["ci_low"] < 0 < per["rule"]["seed_level_diff"]["ci_high"]
    # "the paired difference between PPO and the best constant excludes zero against PPO"
    assert per["best_constant"]["scenario_level_diff"]["ci_high"] < 0
    assert summ[sel]["total_reward"] > summ["rule"]["total_reward"]
    assert res["carbon"]["is_real"] is False and res["carbon"]["flat_curve"] is True
