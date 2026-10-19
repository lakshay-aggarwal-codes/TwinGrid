"""Task 22: the issue register does not claim more than the tree shows. Static, no network, no training."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = (ROOT / "docs" / "audit" / "TwinGrid_Issue_Register.md").read_text(encoding="utf-8")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _heading(issue: str) -> str:
    m = re.search(rf"^### {issue} .*$", REGISTER, re.M)
    assert m, f"{issue} missing from the register"
    return m.group(0)


def test_every_issue_heading_names_a_status():
    ids = re.findall(r"^### (TG-A-\d+) ", REGISTER, re.M)
    assert len(ids) >= 20
    for i in ids:
        assert re.search(r"FIXED|CONFIRMED-OPEN|PARTIAL|RISK|FEATURE", _heading(i)), i


def test_fixed_claims_have_their_code_present():
    needles = {
        "TG-A-01": ("src/policy_evaluation.py", "class PhysicsMismatchError"),
        "TG-A-02": ("src/policy_evaluation.py", "HARD_CONSTRAINT_METRICS"),
        "TG-A-03": ("src/rl/env.py", "class UnsupportedPhysicsVersionForRL"),
        "TG-A-04": ("src/baselines/config.py", "def assert_eval_physics_matches_lineage"),
        "TG-A-12": ("src/policy_evaluation.py", "PUE_METRIC"),
        "TG-A-17": ("twin-stream-insight-main/src/evaluation/schema.ts", "z.literal(2)"),
        "TG-A-21": ("twin-stream-insight-main/src/components/evaluation/PolicyComparison.tsx", "PolicyComparison"),
    }
    for issue, (rel, needle) in needles.items():
        assert "FIXED" in _heading(issue), issue
        assert needle in _read(rel), (issue, rel, needle)


def test_retired_twin_is_gone_while_the_register_says_fixed():
    assert "FIXED" in _heading("TG-A-05")
    assert not (ROOT / "src" / "digital_twin_optimized.py").exists()


def test_open_items_stay_open_while_the_tree_still_has_the_defect():
    if "min: 5, max: 15" in _read("twin-stream-insight-main/src/features/what-if-lab/model.ts"):
        assert "CONFIRMED-OPEN" in _heading("TG-A-19")
    if not (ROOT / "data" / "cleaned" / "carbon_intensity.csv").exists():
        assert "CONFIRMED-OPEN" in _heading("TG-A-11")
    pid = _read("configs/baselines/pid.json")
    if '"tuner_version": "baselines-tuner/3"' not in pid:
        assert "CONFIRMED-OPEN in the shipped artifact" in _heading("TG-A-16")


def test_patent_wording_is_gone_and_the_register_says_so():
    hits = [
        ln
        for p in (ROOT / "src").rglob("*.py")
        for ln in p.read_text(encoding="utf-8").splitlines()
        if "patent" in ln.lower()
    ]
    assert all('"patent_objective"' in ln for ln in hits)
    assert "FIXED" in _heading("TG-A-10")
