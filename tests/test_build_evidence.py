"""Task 26: scripts/build_evidence.py turns the repo's own documents into the Evidence page data.

No network, no database, no browser. Fixture trees are built in temporary directories; one test checks the real tree.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_evidence", ROOT / "scripts" / "build_evidence.py")
be = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(be)

CLAIMS = """# Claims ledger

| ID | Claim | Status | Evidence | Boundary |
|---|---|---|---|---|
| C-01 | A simulated twin. | fact | `a.md`, `b/c.py` | Not a real facility. |
| C-02 | Pipes `x | y` inside code stay in one cell. | result | `a.md` | One run. |
| C-03 | Nobody has measured it. | hypothesis | `a.md` | Not measured. |
"""

LIMITS = """# Shared limitations

## 1. Synthetic data
Intro paragraph that
wraps over two lines.

- **First point.** Text of the
  first point.
- Plain bullet.

## 2. What is unevaluated or negative today
| Model | Plain statement |
|---|---|
| Forecaster | One run, no baseline. |
| PPO | Outcome `C`. |

## 4. Wording rules for the UI
Allowed: simulated.
"""


def _ppo(outcome: str = "C", claim: str = "none", at: str = "2026-10-19T00:00:00+00:00") -> dict:
    return {
        "decision": {"outcome": outcome, "claim_allowed": claim, "reason": "why", "selected_seed": 2},
        "physics_version_executed": "1",
        "carbon": {"is_real": False},
        "preregistration_sha256": "ab",
        "scenario_set_id": "id1",
        "scenario_sets": {"test": {"n": 60}},
        "selection": {"best_constant": {"name": "constant[22.75C,closed_loop]"}},
        "environment": {"generated_at_utc": at},
        "summary_test_mean_per_episode": {
            "rule": {"total_reward": -54.851692, "energy_kwh": 9622.2, "water_L": 4850.79, "mean_pue": 1.2358783},
            "ppo_seed_0": {"total_reward": -56.2},
        },
    }


def _tree(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="evidence_"))
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def test_claims_parse_into_the_documented_shape():
    rows = be.parse_claims(CLAIMS)
    assert [r["id"] for r in rows] == ["C-01", "C-02", "C-03"]
    assert set(rows[0]) == {"id", "text", "kind", "evidence_paths", "limit"}
    assert rows[0]["evidence_paths"] == ["a.md", "b/c.py"]
    assert rows[1]["text"] == "Pipes x | y inside code stay in one cell."
    assert rows[2]["kind"] == "hypothesis"


def test_unknown_claim_status_stops_the_build():
    bad = CLAIMS.replace("hypothesis", "proven")
    try:
        be.parse_claims(bad)
    except be.EvidenceError as exc:
        assert "C-03" in str(exc)
    else:
        raise AssertionError("expected EvidenceError")


def test_limitations_split_into_sections_and_model_status():
    d = be.parse_limitations(LIMITS)
    assert d["model_status"] == [
        {"model": "Forecaster", "statement": "One run, no baseline."},
        {"model": "PPO", "statement": "Outcome C."},
    ]
    titles = [s["title"] for s in d["sections"]]
    assert titles == ["Synthetic data"]  # the status table section has no bullets; wording rules are skipped
    items = d["sections"][0]["items"]
    assert items[0] == {"title": "", "text": "Intro paragraph that wraps over two lines."}
    assert items[1] == {"title": "First point.", "text": "Text of the first point."}
    assert items[2] == {"title": "", "text": "Plain bullet."}


def test_missing_sources_are_recorded_as_not_recorded_never_invented():
    root = _tree({"README.md": "x"})
    ppo = be.build_ppo(root)
    assert ppo["outcome"] == be.NOT_RECORDED and ppo["claim_allowed"] == be.NOT_RECORDED
    assert ppo["runs"] == [] and ppo["policies"] == []
    assert be.build_status(root) == {"recorded": False, "note": "not recorded for this build", "checks": []}


def test_ppo_summary_reads_every_run_and_agrees_only_when_they_agree():
    files = {
        "reports/policy_evaluation_physics1/full_x/results.json": json.dumps(_ppo()),
        "reports/policy_evaluation_physics1/rerun/full_x/results.json": json.dumps(
            _ppo(at="2026-10-21T00:00:00+00:00")
        ),
    }
    ppo = be.build_ppo(_tree(files))
    assert ppo["outcome"] == "C" and ppo["claim_allowed"] == "none"
    assert len(ppo["runs"]) == 2
    assert ppo["policies_source"].startswith("reports/policy_evaluation_physics1/rerun/")  # latest run
    assert ppo["policies"][0] == {
        "policy": "ppo_seed_0",
        "total_reward": -56.2,
        "energy_kwh": be.NOT_RECORDED,
        "water_L": be.NOT_RECORDED,
        "mean_pue": be.NOT_RECORDED,
    }
    assert ppo["policies"][1]["total_reward"] == -54.8517

    files["reports/policy_evaluation_physics1/rerun/full_x/results.json"] = json.dumps(_ppo(outcome="A", claim="some"))
    ppo = be.build_ppo(_tree(files))
    assert ppo["outcome"] == "runs disagree" and ppo["claim_allowed"] == "runs disagree"


def test_status_file_is_validated_not_silently_dropped():
    ok = {"checks": [{"name": "backend", "result": "pass", "counts": "1 passed", "extra": "ignored"}], "commit": "abc"}
    st = be.build_status(_tree({"evidence/status.json": json.dumps(ok)}))
    assert st == {
        "recorded": True,
        "checks": [{"name": "backend", "result": "pass", "counts": "1 passed"}],
        "commit": "abc",
    }
    for bad in ("{not json", json.dumps({"checks": [{"name": "x", "result": "green"}]}), json.dumps([1])):
        try:
            be.build_status(_tree({"evidence/status.json": bad}))
        except be.EvidenceError:
            continue
        raise AssertionError(f"expected EvidenceError for {bad!r}")


def test_skills_paths_must_exist():
    try:
        be.build_skills(_tree({"README.md": "x"}))
    except be.EvidenceError as exc:
        assert "not in the repository" in str(exc)
    else:
        raise AssertionError("expected EvidenceError")


def test_check_detects_missing_and_stale_and_write_fixes_it():
    root = _tree({"docs/CLAIMS.md": CLAIMS, "docs/model_cards/LIMITATIONS.md": LIMITS})
    # a minimal tree has no skill files, so give it exactly those
    for _, _, files in be.SKILLS:
        for path, _ in files:
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
    assert be.main(["--check"], root=root) == 1  # nothing generated yet
    assert be.main([], root=root) == 0
    assert be.main(["--check"], root=root) == 0
    changed = CLAIMS.replace("A simulated twin.", "A different claim.")
    (root / "docs" / "CLAIMS.md").write_text(changed, encoding="utf-8")
    assert be.main(["--check"], root=root) == 1  # source changed, generated file is stale


def test_output_is_deterministic():
    a = be.render(be.build_all(ROOT))
    b = be.render(be.build_all(ROOT))
    assert a == b


def test_committed_generated_files_match_the_repository():
    """The same check CI runs: python scripts/build_evidence.py --check."""
    assert be.main(["--check"], root=ROOT) == 0


def test_real_tree_claims_cover_the_ledger_and_keep_the_ppo_negative_result():
    built = be.build_all(ROOT)
    ids = {r["id"] for r in built["claims.json"]}
    assert len(ids) >= 30 and "C-08" in ids
    ppo = built["ppo_result.json"]
    assert ppo["outcome"] == "C" and ppo["claim_allowed"] == "none"
    for r in built["claims.json"]:
        for p in r["evidence_paths"]:
            assert (ROOT / p).exists(), (r["id"], p)
