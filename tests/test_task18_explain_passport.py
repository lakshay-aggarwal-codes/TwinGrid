"""Task 18: pure logic of src/alert_explain.py and src/model_passport.py (no app, no database, no TensorFlow)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import alert_explain as ae
from src import model_passport as mp

ROOT = Path(__file__).resolve().parents[1]
COLS = ["water_flow_lpm", "water_pressure_bar", "server_outlet_temp_C", "it_power_kw", "humidity_pct"]
LO = [0.0, 2.0, 30.0, 200.0, 20.0]
HI = [100.0, 4.0, 50.0, 500.0, 100.0]


def vals(**over):
    base = {
        "water_flow_lpm": 50.0,
        "water_pressure_bar": 3.0,
        "server_outlet_temp_C": 40.0,
        "it_power_kw": 350.0,
        "humidity_pct": 60.0,
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ explanation numbers


def test_centre_of_range_is_zero_distance_and_edges_are_one():
    rows = {r["feature"]: r for r in ae.feature_deviations(vals(), COLS, LO, HI)}
    assert rows["water_flow_lpm"]["position"] == pytest.approx(0.5)
    assert rows["water_flow_lpm"]["centre_distance"] == pytest.approx(0.0)
    assert rows["water_pressure_bar"]["centre_distance"] == pytest.approx(0.0)
    edge = {r["feature"]: r for r in ae.feature_deviations(vals(server_outlet_temp_C=50.0), COLS, LO, HI)}
    assert edge["server_outlet_temp_C"]["centre_distance"] == pytest.approx(1.0)
    assert edge["server_outlet_temp_C"]["outside_range"] is False


def test_outside_range_numbers():
    rows = {
        r["feature"]: r
        for r in ae.feature_deviations(vals(server_outlet_temp_C=55.0, water_pressure_bar=1.0), COLS, LO, HI)
    }
    hot = rows["server_outlet_temp_C"]
    assert hot["position"] == pytest.approx(1.25)
    assert hot["outside_range_by"] == pytest.approx(0.25)
    assert hot["centre_distance"] == pytest.approx(1.5)
    assert hot["outside_range"] is True
    low = rows["water_pressure_bar"]
    assert low["position"] == pytest.approx(-0.5)
    assert low["outside_range_by"] == pytest.approx(0.5)
    assert low["centre_distance"] == pytest.approx(2.0)


def test_ranking_largest_first_ties_by_column_order():
    rows = ae.feature_deviations(vals(water_pressure_bar=1.0, server_outlet_temp_C=55.0), COLS, LO, HI)
    assert [r["feature"] for r in rows][:2] == ["water_pressure_bar", "server_outlet_temp_C"]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5]
    # the three centred signals tie at 0.0 -> original column order
    assert [r["feature"] for r in rows][2:] == ["water_flow_lpm", "it_power_kw", "humidity_pct"]


def test_deterministic_and_does_not_mutate_input():
    v = vals(server_outlet_temp_C=47.0)
    before = dict(v)
    assert ae.feature_deviations(v, COLS, LO, HI) == ae.feature_deviations(v, COLS, LO, HI)
    assert v == before


@pytest.mark.parametrize(
    "values",
    [
        vals(it_power_kw=None),
        vals(humidity_pct=float("nan")),
        vals(water_flow_lpm=float("inf")),
        {k: v for k, v in vals().items() if k != "it_power_kw"},
    ],
)
def test_missing_or_non_finite_input_is_an_error_not_a_zero(values):
    with pytest.raises(ValueError):
        ae.feature_deviations(values, COLS, LO, HI)


def test_degenerate_training_range_is_an_error():
    with pytest.raises(ValueError):
        ae.feature_deviations(vals(), COLS, LO, [100.0, 2.0, 50.0, 500.0, 100.0])
    with pytest.raises(ValueError):
        ae.feature_deviations(vals(), COLS, LO[:4], HI)


def test_score_vs_threshold_numbers_and_severity_rule():
    r = ae.score_vs_threshold(0.03, 0.012)
    assert r["ratio"] == pytest.approx(2.5)
    assert r["margin"] == pytest.approx(0.018)
    assert r["over_threshold"] is True
    assert r["critical_above"] == pytest.approx(0.024)
    assert r["severity_by_rule"] == "CRITICAL"
    assert ae.score_vs_threshold(0.02, 0.012)["severity_by_rule"] == "WARNING"
    assert ae.score_vs_threshold(0.01, 0.012)["over_threshold"] is False
    for bad in [(float("nan"), 1.0), (1.0, 0.0), (1.0, -1.0), (True, 1.0)]:
        with pytest.raises(ValueError):
            ae.score_vs_threshold(*bad)


def test_severity_rule_matches_the_pipeline_rule():
    from api.services.anomaly_service import alert_severity

    for score in (0.001, 0.0122, 0.0245, 0.0246, 0.5):
        assert ae.score_vs_threshold(score, 0.0122)["severity_by_rule"] == alert_severity(score, 0.0122)


def test_real_scaler_ranges_load_and_place_a_typical_reading():
    cfg = json.loads((ROOT / "models/anomaly/config.json").read_text())
    arrays = json.loads((ROOT / "models/anomaly/scaler.json").read_text())["arrays"]
    lo, hi = arrays["data_min_"]["values"], arrays["data_max_"]["values"]
    mid = {c: (a + b) / 2 for c, a, b in zip(cfg["feature_columns"], lo, hi)}
    rows = ae.feature_deviations(mid, cfg["feature_columns"], lo, hi)
    assert all(r["centre_distance"] == pytest.approx(0.0) for r in rows)


# ------------------------------------------------------------------ passport shape


def registry():
    return json.loads((ROOT / "models/registry.json").read_text())["artifacts"]


def passport(decision=None):
    return mp.build_passport(
        registry(),
        decision=decision,
        detector={"threshold": 0.0122, "threshold_percentile": 99.5, "feature_columns": COLS},
    )


REQUIRED = {
    "model_id", "name", "kind", "version", "status", "status_reason", "loadable", "created_at_utc", "data_origin",
    "data_origin_basis", "data_source", "dataset_id", "physics_version", "metrics_label", "headline_metrics",
    "limitations", "limitations_source", "claim_boundary", "evaluation",
}  # fmt: skip


def test_passport_shape_one_entry_per_registry_artifact_in_order():
    p = passport()
    assert p["schema_version"] == 1 and p["origin"] == "registry" and p["metrics_label"] == "synthetic-data result"
    assert [m["model_id"] for m in p["models"]] == [a["model_id"] for a in registry()]
    for m in p["models"]:
        assert REQUIRED <= set(m)
        assert m["data_origin"] == "synthetic"
        assert m["metrics_label"] == "synthetic-data result"
        assert m["limitations"][0] == mp.SHARED_LIMITATION
        assert m["claim_boundary"].endswith(".")


def test_headline_metrics_are_the_registry_numbers_verbatim_and_flat():
    by_id = {m["model_id"]: m for m in passport()["models"]}
    anomaly = next(m for m in by_id.values() if m["kind"] == "anomaly")
    assert {x["name"]: x["value"] for x in anomaly["headline_metrics"]} == {
        "f1": 0.96,
        "precision": 0.9230769230769231,
        "recall": 1.0,
    }
    ppo_q = by_id["ppo_optimizer-20260927T143232Z"]
    names = [x["name"] for x in ppo_q["headline_metrics"]]
    assert (
        "pue_improvement_mean_pct" in names and "pue_improvement_per_seed_pct" not in names
    )  # nested object not flattened
    assert next(x for x in ppo_q["headline_metrics"] if x["name"] == "pue_improvement_mean_pct")[
        "value"
    ] == pytest.approx(-2.267707427967431)
    candidate = by_id["ppo-p1-e2-cd2345024-s0"]
    assert candidate["headline_metrics"] == []  # a candidate has no numbers: none are invented


def test_status_and_loadable_follow_the_registry():
    by_id = {m["model_id"]: m for m in passport()["models"]}
    assert by_id["ppo_optimizer-20260927T143232Z"]["status"] == "quarantined"
    assert by_id["ppo_optimizer-20260927T143232Z"]["loadable"] is False
    assert "Quarantined" in by_id["ppo_optimizer-20260927T143232Z"]["claim_boundary"]
    anomaly = next(m for m in by_id.values() if m["kind"] == "anomaly")
    assert anomaly["status"] == "promoted" and anomaly["loadable"] is True
    assert anomaly["detector"] == {"threshold": 0.0122, "threshold_percentile": 99.5, "feature_columns": COLS}
    assert "detector" not in by_id["ppo-p1-e2-cd2345024-s0"]


def test_ppo_state_is_the_stored_decision_not_implied():
    cand = next(m for m in passport()["models"] if m["model_id"] == "ppo-p1-e2-cd2345024-s0")
    assert cand["evaluation"]["outcome"] == "NOT_EVALUATED" and cand["evaluation"]["claim_allowed"] == "none"
    assert "not evaluated" in cand["evaluation"]["reason"]
    stored = {
        "outcome": "NOT_EVALUATED",
        "claim_allowed": "none",
        "reason": "No PPO candidates were supplied",
        "evaluation_id": "baselines_only_x",
    }
    c2 = next(m for m in passport(stored)["models"] if m["model_id"] == "ppo-p1-e2-cd2345024-s0")
    assert c2["evaluation"] == {
        "outcome": "NOT_EVALUATED", "claim_allowed": "none", "reason": "No PPO candidates were supplied",
        "source": "latest stored evaluation report", "evaluation_id": "baselines_only_x",
    }  # fmt: skip
    assert next(m for m in passport()["models"] if m["kind"] == "anomaly")["evaluation"] is None


def test_no_filesystem_path_leaks_into_the_passport():
    text = json.dumps(passport())
    assert "artifacts_training" not in text and "model.zip" not in text and "sha256" not in text


def test_every_static_limitation_phrase_is_quoted_from_its_model_card():
    for kind, (card, phrases) in mp.KIND_LIMITATIONS.items():
        text = " ".join((ROOT / card).read_text(encoding="utf-8").split())
        for phrase in phrases:
            assert " ".join(phrase.split()) in text, (kind, phrase)
    shared = " ".join((ROOT / "docs/model_cards/LIMITATIONS.md").read_text(encoding="utf-8").split())
    assert " ".join(mp.SHARED_LIMITATION.split()) in shared
    assert " ".join(mp.SHARED_BOUNDARY.split()) in shared


def test_unknown_kind_and_missing_fields_stay_none_never_defaulted():
    m = mp.build_passport_entry({"model_id": "x", "kind": "mystery"}, decision=None, detector=None)
    assert m["kind"] == "mystery" and m["status"] == "unknown" and m["loadable"] is False
    assert m["version"] is None and m["headline_metrics"] == [] and m["evaluation"] is None
