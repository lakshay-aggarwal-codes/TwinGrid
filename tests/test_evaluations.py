"""BC-11 / G-EVAL (BE-G2): GET /api/evaluations and GET /api/evaluations/{evaluation_id}.

Read-only projection: the tests check that nothing is computed, re-ranked or invented, and that ids cannot escape
the reports directory. Real-report tests use the committed baselines-only report (no PPO row, NOT_EVALUATED).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from api.services import evaluation_service as ES
from tests.test_api_routes_smoke import client, viewer  # noqa: F401  (pytest fixtures)

REAL_ID = "baselines_only_0fcafef9d28fd539"
REPO_REPORTS = Path(__file__).resolve().parents[1] / "reports" / "policy_evaluation"

DETAIL_KEYS = {
    "evaluation_id", "source", "origin", "schema_version", "generated_at_utc", "physics_version",
    "scenario_inputs", "carbon", "scenario_set_id", "scenario_sets", "preregistration_sha256", "decision",
    "policies", "selection", "metrics", "outcome_definitions", "ci_level",
}  # fmt: skip


@pytest.fixture
def reports(tmp_path, monkeypatch):
    """A temporary copy of the committed reports directory that the service reads instead of the repo's."""
    dst = tmp_path / "policy_evaluation"
    shutil.copytree(REPO_REPORTS, dst)
    monkeypatch.setattr(ES, "reports_dir", lambda: dst)
    return dst


def _results(reports: Path, evaluation_id: str = REAL_ID) -> dict:
    return json.loads((reports / evaluation_id / "results.json").read_text(encoding="utf-8"))


def _write(reports: Path, evaluation_id: str, results: dict) -> None:
    d = reports / evaluation_id
    d.mkdir(exist_ok=True)
    (d / "results.json").write_text(json.dumps(results), encoding="utf-8")


# ---- auth ------------------------------------------------------------------------------------------------------
async def test_requires_auth(client):  # noqa: F811
    assert (await client.get("/api/evaluations")).status_code in (401, 403)
    assert (await client.get(f"/api/evaluations/{REAL_ID}")).status_code in (401, 403)


# ---- the committed real report ---------------------------------------------------------------------------------
async def test_list_real_report(client, viewer):  # noqa: F811
    r = await client.get("/api/evaluations", headers=viewer)
    assert r.status_code == 200
    items = r.json()["evaluations"]
    assert [i["evaluation_id"] for i in items] == [REAL_ID]
    assert items[0] == {
        "evaluation_id": REAL_ID,
        "source": "policy_evaluation_v1",
        "generated_at_utc": "2026-10-02T02:27:11+00:00",
        "outcome": "NOT_EVALUATED",
        "claim_allowed": "none",
        "ppo_evaluated": False,
    }


async def test_detail_real_report_is_verbatim_and_has_no_ppo_row(client, viewer):  # noqa: F811
    r = await client.get(f"/api/evaluations/{REAL_ID}", headers=viewer)
    assert r.status_code == 200
    d = r.json()
    raw = json.loads((REPO_REPORTS / REAL_ID / "results.json").read_text(encoding="utf-8"))
    assert set(d) == DETAIL_KEYS
    assert d["origin"] == "simulated" and d["source"] == "policy_evaluation_v1"
    assert d["decision"] == raw["decision"]
    assert d["decision"]["outcome"] == "NOT_EVALUATED" and d["decision"]["claim_allowed"] == "none"
    assert [p["policy_id"] for p in d["policies"]] == ["rule", "best_constant"]
    assert [p["kind"] for p in d["policies"]] == ["rule", "best_constant"]
    assert not any(p.get("kind") == "ppo" for p in d["policies"])
    for p in d["policies"]:
        assert p["metrics"] == raw["summary_test_mean_per_episode"][p["policy_id"]]
    for key in ("carbon", "scenario_sets", "scenario_set_id", "selection", "physics_version", "scenario_inputs"):
        assert d[key] == raw[key]
    assert d["preregistration_sha256"] == raw["preregistration_sha256"]
    assert "per_scenario_test" not in d and "environment" not in d
    assert d["carbon"] == {"flat_curve": True, "is_real": False}


async def test_detail_prereg_text_is_copied_verbatim(client, viewer):  # noqa: F811
    d = (await client.get(f"/api/evaluations/{REAL_ID}", headers=viewer)).json()
    prereg = json.loads((REPO_REPORTS / "PREREGISTRATION.json").read_text(encoding="utf-8"))
    assert d["metrics"] == prereg["metrics"]
    assert d["outcome_definitions"] == prereg["outcome_rules"]
    assert set(d["outcome_definitions"]) == {"A", "B", "C"}  # no NOT_EVALUATED definition is invented
    assert d["ci_level"] == prereg["config"]["confidence"] == 0.95
    assert set(d["metrics"]) == set(d["policies"][0]["metrics"])


async def test_no_ci_is_invented_for_baselines_only(client, viewer):  # noqa: F811
    text = json.dumps((await client.get(f"/api/evaluations/{REAL_ID}", headers=viewer)).json())
    for forbidden in ("ci_low", "ci_high", "evaluation_status"):
        assert forbidden not in text


# ---- ids -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        "nope",
        "..",
        "%2e%2e",
        "..%2F..%2Fetc",
        "PREREGISTRATION.json",
        "a" * 300,
        "bad id",
        "baselines_only_0fcafef9d28fd539%00",
    ],
)
async def test_unknown_or_hostile_ids_are_404(client, viewer, bad):  # noqa: F811
    r = await client.get(f"/api/evaluations/{bad}", headers=viewer)
    assert r.status_code == 404


def test_loader_never_touches_paths_outside_the_listing(reports):
    (reports.parent / "secret").mkdir()
    (reports.parent / "secret" / "results.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    for bad in ("../secret", "..", "/etc", "secret/../..", ""):
        assert ES._load_report(bad) is None


# ---- ordering, kinds, unknown values ---------------------------------------------------------------------------
def test_policy_order_is_fixed_and_not_metric_ordered(reports):
    raw = _results(reports)
    s = raw["summary_test_mean_per_episode"]
    m = s["rule"]
    raw["summary_test_mean_per_episode"] = {
        "ppo_seed_3": {**m, "energy_kwh": 1.0},  # best energy on purpose: it must not move
        "best_constant": s["best_constant"],
        "ppo_seed_1": {**m, "energy_kwh": 99999.0},
        "rule": s["rule"],
        "weird": dict(m),
    }
    _write(reports, "ppo_case_0000000000000000", raw)
    d = ES.get_evaluation("ppo_case_0000000000000000")
    assert [p["policy_id"] for p in d["policies"]] == ["rule", "best_constant", "ppo_seed_3", "ppo_seed_1", "weird"]
    assert [p.get("kind") for p in d["policies"]] == ["rule", "best_constant", "ppo", "ppo", None]
    assert ES.list_evaluations()["evaluations"][0]["ppo_evaluated"] in (True, False)
    item = next(i for i in ES.list_evaluations()["evaluations"] if i["evaluation_id"] == "ppo_case_0000000000000000")
    assert item["ppo_evaluated"] is True


def test_decision_with_ppo_detail_passes_through_unchanged(reports):
    raw = _results(reports)
    decision = {
        "outcome": "B",
        "reason": "synthetic shape fixture",
        "claim_allowed": "none",
        "selected_seed": 2,
        "detail": {"per_baseline": {"rule": {"seed_level_diff": {"n": 5, "ci_low": -1.0, "ci_high": 2.0}}}},
        "future_unknown_key": {"x": 1},
    }
    raw["decision"] = decision
    _write(reports, "shape_b_0000000000000000", raw)
    assert ES.get_evaluation("shape_b_0000000000000000")["decision"] == decision


def test_unknown_outcome_value_is_not_normalised(reports):
    raw = _results(reports)
    raw["decision"] = {"outcome": "SOMETHING_NEW", "claim_allowed": "whatever"}
    _write(reports, "unk_0000000000000000", raw)
    item = next(i for i in ES.list_evaluations()["evaluations"] if i["evaluation_id"] == "unk_0000000000000000")
    assert (item["outcome"], item["claim_allowed"]) == ("SOMETHING_NEW", "whatever")


def test_missing_decision_fields_stay_absent_not_defaulted(reports):
    raw = _results(reports)
    raw["decision"] = {}
    _write(reports, "nodec_0000000000000000", raw)
    item = next(i for i in ES.list_evaluations()["evaluations"] if i["evaluation_id"] == "nodec_0000000000000000")
    assert item["outcome"] is None and item["claim_allowed"] is None


# ---- pre-registration binding ----------------------------------------------------------------------------------
def test_prereg_text_withheld_when_hash_differs(reports):
    raw = _results(reports)
    raw["preregistration_sha256"] = "0" * 64
    _write(reports, "othercfg_0000000000000000", raw)
    d = ES.get_evaluation("othercfg_0000000000000000")
    for key in ("metrics", "outcome_definitions", "ci_level"):
        assert key not in d


def test_prereg_text_withheld_when_file_missing(reports):
    (reports / "PREREGISTRATION.json").unlink()
    d = ES.get_evaluation(REAL_ID)
    for key in ("metrics", "outcome_definitions", "ci_level"):
        assert key not in d


# ---- listing robustness ----------------------------------------------------------------------------------------
def test_list_skips_unreadable_wrong_version_and_non_directories(reports):
    (reports / "corrupt_x").mkdir()
    (reports / "corrupt_x" / "results.json").write_text("{not json", encoding="utf-8")
    raw = _results(reports)
    raw["schema_version"] = 2
    _write(reports, "v2_x", raw)
    (reports / "empty_dir").mkdir()
    (reports / "stray.json").write_text("{}", encoding="utf-8")
    assert [i["evaluation_id"] for i in ES.list_evaluations()["evaluations"]] == [REAL_ID]
    with pytest.raises(Exception) as exc:
        ES.get_evaluation("v2_x")
    assert getattr(exc.value, "status_code", None) == 404


def test_list_is_newest_first(reports):
    older = _results(reports)
    older["environment"] = {"generated_at_utc": "2026-01-01T00:00:00+00:00"}
    _write(reports, "older_0000000000000000", older)
    newer = _results(reports)
    newer["environment"] = {"generated_at_utc": "2026-12-31T00:00:00+00:00"}
    _write(reports, "newer_0000000000000000", newer)
    ids = [i["evaluation_id"] for i in ES.list_evaluations()["evaluations"]]
    assert ids == ["newer_0000000000000000", REAL_ID, "older_0000000000000000"]


def test_missing_reports_directory_is_an_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(ES, "reports_dir", lambda: tmp_path / "does-not-exist")
    assert ES.list_evaluations() == {"evaluations": []}


def test_oversized_report_is_skipped(reports, monkeypatch):
    monkeypatch.setattr(ES, "MAX_REPORT_BYTES", 10)
    assert ES.list_evaluations() == {"evaluations": []}


def test_service_has_no_writes_or_statistics():
    src = Path(ES.__file__).read_text(encoding="utf-8")
    for token in ("write_text", "open(", "numpy", "scipy", "statistics", "sorted(policies", ".sort(key=lambda p"):
        assert token not in src, token
