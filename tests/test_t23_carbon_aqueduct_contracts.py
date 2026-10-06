"""T23 -- CarbonSignal (roadmap 13.6) and Aqueduct semantics (13.7)."""

from __future__ import annotations

import ast
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from src import carbon_provider as cp
from src.carbon_provider import (
    CarbonSignal,
    carbon_basis,
    fallback_signal,
    format_carbon_reduction,
    load_carbon_signal,
    load_diurnal_carbon_intensity,
    signal_for_curve,
)
from src.ingestion import water_stress_aqueduct as aq

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc


def _write_carbon(tmp_path, rows, meta=None, name="carbon_intensity.csv"):
    f = tmp_path / name
    pd.DataFrame(rows, columns=["zone", "timestamp_utc", "carbon_intensity_gco2_per_kwh"]).to_csv(f, index=False)
    if meta is not None:
        (tmp_path / cp.CARBON_META_FILENAME).write_text(json.dumps(meta))
    return f


def _full_day(zone="IN-NO", base=100.0):
    return [(zone, f"2026-03-01T{h:02d}:00:00Z", base + h) for h in range(24)]


# --------------------------------------------------------------------------- fallback labelling
def test_absent_file_gives_a_labelled_constant_assumption(tmp_path):
    sig = load_carbon_signal(path=tmp_path / "nope.csv")
    assert sig.is_fallback and sig.semantic == "constant_assumption" and sig.aggregation == "constant"
    assert sig.values == (475.0,) and sig.timestamps_utc == ()
    assert sig.license_ref is None and sig.retrieved_at is None
    assert np.all(sig.curve_by_site_local_hour == 475.0) and sig.curve_by_site_local_hour.shape == (24,)
    assert carbon_basis(sig)["time_varying_signal"] is False


def test_constant_assumption_can_never_claim_to_be_data():
    with pytest.raises(ValueError):
        CarbonSignal(**{**fallback_signal().__dict__, "is_fallback": False})
    with pytest.raises(ValueError):
        CarbonSignal(**{**fallback_signal().__dict__, "semantic": "real"})


def test_backward_compatible_tuple_api(tmp_path):
    curve, is_real = load_diurnal_carbon_intensity()  # repo has no cleaned file
    assert curve.shape == (24,) and np.all(curve == 475.0) and is_real is False


# --------------------------------------------------------------------------- semantic is never guessed
def test_file_without_documented_semantic_is_unknown_not_average(tmp_path):
    sig = load_carbon_signal(path=_write_carbon(tmp_path, _full_day()))
    assert sig.semantic == "unknown" and sig.license_ref is None and sig.is_fallback is False
    assert carbon_basis(sig)["semantic"] == "unknown"


@pytest.mark.parametrize("claimed", ["average", "marginal"])
def test_semantic_comes_only_from_the_sidecar(tmp_path, claimed):
    meta = {
        "semantic": claimed,
        "source_version": "v9",
        "retrieved_at": "2026-09-01T00:00:00Z",
        "license_ref": "CC-BY-4.0",
    }
    sig = load_carbon_signal(path=_write_carbon(tmp_path, _full_day(), meta))
    assert (sig.semantic, sig.source_version, sig.license_ref) == (claimed, "v9", "CC-BY-4.0")
    assert sig.retrieved_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert sig.aggregation == "diurnal_mean" and sig.zone == "IN-NO" and sig.resolution_s == 3600


@pytest.mark.parametrize("bad", ["real", "AVERAGE", "", None, 3, "constant_assumption"])
def test_invalid_sidecar_semantic_is_recorded_unknown(tmp_path, bad):
    sig = load_carbon_signal(path=_write_carbon(tmp_path, _full_day(), {"semantic": bad}))
    assert sig.semantic == "unknown"


def test_unreadable_sidecar_is_unknown(tmp_path):
    f = _write_carbon(tmp_path, _full_day())
    (tmp_path / cp.CARBON_META_FILENAME).write_text("{not json")
    assert load_carbon_signal(path=f).semantic == "unknown"


def test_hours_without_data_make_the_signal_a_fallback(tmp_path):
    sig = load_carbon_signal(path=_write_carbon(tmp_path, _full_day()[:12], {"semantic": "average"}))
    assert sig.is_fallback is True and len(sig.missing_hours) > 0
    assert sig.curve_by_site_local_hour.shape == (24,)


def test_bad_rows_are_dropped_and_all_bad_falls_back(tmp_path):
    rows = _full_day() + [("IN-NO", "garbage", 5.0), ("IN-NO", "2026-03-02T00:00:00Z", float("nan"))]
    assert load_carbon_signal(path=_write_carbon(tmp_path, rows)).is_fallback is False
    sig = load_carbon_signal(path=_write_carbon(tmp_path, [("Z", "garbage", 1.0)], name="b.csv"))
    assert sig.is_fallback and sig.semantic == "constant_assumption"


def test_caller_supplied_curve_is_labelled_unestablished():
    assert signal_for_curve(np.full(24, 475.0)).semantic == "constant_assumption"
    s = signal_for_curve(np.linspace(300, 500, 24))
    assert s.semantic == "unknown" and s.is_fallback is True


# --------------------------------------------------------------------------- UTC <-> site-local hour mapping
def test_utc_1830_is_ist_midnight(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_TIMEZONE", "Asia/Kolkata")
    rows = [("Z", "2026-03-01T18:30:00Z", 111.0), ("Z", "2026-03-01T12:00:00Z", 222.0)]
    sig = load_carbon_signal(path=_write_carbon(tmp_path, rows))
    curve = sig.curve_by_site_local_hour
    assert curve[0] == 111.0  # 18:30 UTC == 00:00 IST (next day)
    assert curve[17] == 222.0  # 12:00 UTC == 17:30 IST -> hour 17
    assert sig.site_timezone == "Asia/Kolkata"
    assert curve[5] == 475.0 and set(sig.missing_hours) == set(range(24)) - {0, 17}  # unmapped hours are labelled


@pytest.mark.parametrize(
    "tz, utc_ts, local_hour",
    [
        ("UTC", "2026-03-01T07:00:00Z", 7),
        ("America/New_York", "2026-07-01T16:00:00Z", 12),
        ("America/New_York", "2026-01-01T16:00:00Z", 11),
    ],
)
def test_hour_mapping_follows_the_site_zone_including_dst(tmp_path, monkeypatch, tz, utc_ts, local_hour):
    monkeypatch.setenv("SITE_TIMEZONE", tz)
    sig = load_carbon_signal(path=_write_carbon(tmp_path, [("Z", utc_ts, 321.0)]))
    assert sig.curve_by_site_local_hour[local_hour] == 321.0


def test_signal_remembers_the_zone_it_was_built_for(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_TIMEZONE", "Asia/Kolkata")
    sig = load_carbon_signal(path=_write_carbon(tmp_path, [("Z", "2026-03-01T18:30:00Z", 1.0)]))
    monkeypatch.setenv("SITE_TIMEZONE", "UTC")  # changing the env later must not silently remap an existing signal
    assert sig.curve_by_site_local_hour[0] == 1.0


def test_naive_timestamps_in_the_utc_column_are_read_as_utc_and_offsets_win(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_TIMEZONE", "UTC")
    rows = [("Z", "2026-03-01 05:00:00", 10.0), ("Z", "2026-03-01T10:30:00+05:30", 20.0)]
    curve = load_carbon_signal(path=_write_carbon(tmp_path, rows)).curve_by_site_local_hour
    assert curve[5] == 15.0  # 05:00 UTC (naive column) and 10:30+05:30 == 05:00 UTC


# --------------------------------------------------------------------------- labels propagate
def test_fallback_flag_propagates_to_optimizer_env_and_config_label(tmp_path):
    from src.optimizer import DataCentreEnv, JointOptimizer

    with mock.patch.object(cp, "CLEANED_CARBON_PATH", tmp_path / "absent.csv"):
        env = DataCentreEnv(seed=0)
        opt = JointOptimizer(seed=0)
    for b in (env.carbon_basis, opt.carbon_basis):
        assert b["is_fallback"] is True and b["semantic"] == "constant_assumption"
    label = opt._objective_label()
    assert "real grid carbon" not in label and "ASSUMED" in label and "is_fallback=true" in label


def test_config_json_label_says_real_only_if_not_fallback(tmp_path):
    from src.optimizer import JointOptimizer

    f = _write_carbon(tmp_path, _full_day(), {"semantic": "average", "license_ref": "x"})
    with mock.patch.object(cp, "CLEANED_CARBON_PATH", f):
        opt = JointOptimizer(seed=0)
    assert opt.carbon_basis["is_fallback"] is False and opt.carbon_basis["semantic"] == "average"
    label = opt._objective_label()
    assert (
        "is_fallback=false" in label
        and "average" in label
        and "diurnal_mean" in label
        and "modelled, not measured" in label
    )
    assert "real grid carbon" not in label  # even then: never an unqualified 'real'


def test_optimizer_save_writes_carbon_signal_and_no_real_grid_claim(tmp_path):
    from src.optimizer import JointOptimizer

    class _M:
        def save(self, p):
            (tmp_path / "ppo_model.zip").write_bytes(b"x")

    with mock.patch.object(cp, "CLEANED_CARBON_PATH", tmp_path / "absent.csv"):
        opt = JointOptimizer(seed=0)
    opt._model = _M()
    opt.save(tmp_path)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["carbon_signal"]["is_fallback"] is True and cfg["carbon_signal"]["semantic"] == "constant_assumption"
    assert "real grid carbon" not in cfg["patent_objective"].lower()


def test_checked_in_config_json_labels_the_carbon_signal_as_an_assumption():
    cfg = json.loads((ROOT / "models" / "optimizer" / "config.json").read_text())
    text = cfg["patent_objective"].lower()
    assert "real grid carbon" not in text and "real carbon" not in text
    assert cfg["carbon_signal"]["is_fallback"] is True and cfg["carbon_signal"]["semantic"] == "constant_assumption"
    assert set(cfg["carbon_intensity_by_hour"]) == {475.0}


def test_loading_a_pre_t23_artifact_labels_its_curve_unestablished(tmp_path):
    from src.optimizer import JointOptimizer

    cfg = {"alpha": 0.5, "beta": 0.3, "gamma": 0.2, "carbon_intensity_by_hour": [400.0 + h for h in range(24)]}
    opt = JointOptimizer(seed=0, carbon_intensity_by_hour=np.array(cfg["carbon_intensity_by_hour"]))
    assert opt.carbon_basis["is_fallback"] is True and opt.carbon_basis["semantic"] == "unknown"


def _tick_payload(monkeypatch, tmp_path, carbon_path=None):
    import api.services.live_broadcast_service as lbs
    from tests.characterization import golden_support as gs

    monkeypatch.setattr(lbs, "_label_cache", None)
    monkeypatch.setattr(cp, "CLEANED_CARBON_PATH", carbon_path or tmp_path / "absent.csv")

    async def go():
        with gs.live_tick_environment():
            return await lbs._tick()

    return asyncio.run(go())


def test_ws_payload_carries_carbon_and_water_labels_fallback(monkeypatch, tmp_path):
    p = _tick_payload(monkeypatch, tmp_path)
    assert p["carbon_is_fallback"] is True and p["carbon_semantic"] == "constant_assumption"
    assert p["carbon_aggregation"] == "constant"
    assert p["water_stress_kind"] == "scenario"
    assert p["water_stress"] == p["water_stress_scenario"]  # legacy key equals the scenario value
    assert p["water_stress_baseline"] is None  # no Aqueduct file here
    meta = p["water_stress_baseline_meta"]
    assert meta["geography"] == "country" and meta["temporal"] == "annual" and meta["available"] is False
    assert meta["field"] == "bws_score" and meta["release"] == "Y2023M07D05"
    json.dumps(p)  # plain JSON types


def test_ws_payload_labels_a_loaded_file_as_unknown_until_documented(monkeypatch, tmp_path):
    import api.services.live_broadcast_service as lbs

    f = _write_carbon(tmp_path, _full_day())
    # the golden harness pins the twin's own path to "absent"; point the label loader at the test file
    monkeypatch.setattr(lbs, "load_carbon_signal", lambda: cp.load_carbon_signal(path=f))
    p = _tick_payload(monkeypatch, tmp_path)
    assert p["carbon_is_fallback"] is False and p["carbon_semantic"] == "unknown"
    assert p["carbon_aggregation"] == "diurnal_mean"


# --------------------------------------------------------------------------- report guard
def test_report_refuses_carbon_reduction_when_fallback_or_unknown(tmp_path):
    for sig in (
        fallback_signal(),
        signal_for_curve(np.linspace(300, 500, 24)),
        load_carbon_signal(path=_write_carbon(tmp_path, _full_day())),  # semantic unknown
    ):
        out = format_carbon_reduction(sig, 12.3)
        assert "12.3" not in out and "No carbon reduction is claimed" in out


def test_report_with_documented_signal_is_labelled_modelled_not_demonstrated(tmp_path):
    sig = load_carbon_signal(path=_write_carbon(tmp_path, _full_day(), {"semantic": "marginal"}))
    out = format_carbon_reduction(sig, 12.3)
    assert "+12.3%" in out and "marginal" in out and "modelled, not measured" in out
    assert "demonstrated" not in out.replace("not evidence of carbon-aware optimisation", "")
    assert "average" not in out  # average is never called marginal, and vice versa


def test_average_is_never_described_as_marginal(tmp_path):
    sig = load_carbon_signal(path=_write_carbon(tmp_path, _full_day(), {"semantic": "average"}))
    assert "marginal" not in carbon_basis(sig)["statement"] and "average" in carbon_basis(sig)["statement"]


# --------------------------------------------------------------------------- Aqueduct
def _aq_table():
    rows = []
    for name, scores in {
        "India": [2.0, 4.0, 9999.0, -9999.0],
        "Norway": [0.0, 1.0],
        "Peru": [5.0, -9999.0],
        "Mars": [-9999.0],
    }.items():
        for i, sc in enumerate(scores):
            rows.append({"name_0": name, "bws_score": sc, "bws_raw": 9999.0 if sc == 9999.0 else 0.5})
    return pd.DataFrame(rows)


def test_sentinel_rows_are_excluded_from_means_and_minmax():
    base = aq.country_baseline(_aq_table(), "India")
    # valid scores overall: 2,4,0,1,5 -> min 0, max 5; India valid mean = 3.0 -> 0.6 (sentinels not averaged in)
    assert base.value == pytest.approx(0.6)
    c = base.meta["counts"]
    assert c["sentinel_rows_excluded"] == 4 and c["country_rows"] == 4 and c["country_rows_used"] == 2


def test_all_sentinel_country_has_no_baseline_not_zero_and_not_high():
    base = aq.country_baseline(_aq_table(), "Mars")
    assert base.value is None and base.meta["available"] is False
    assert aq.country_baseline(_aq_table(), "Nowhere").value is None


def test_bws_raw_9999_is_not_read_as_high_stress():
    df = pd.DataFrame({"name_0": ["A", "A", "B"], "bws_score": [1.0, 3.0, 2.0], "bws_raw": [9999.0, 0.2, 0.1]})
    assert aq.country_baseline(df, "A").value == pytest.approx(0.5)  # from bws_score only; raw sentinel ignored
    counts = aq.sentinel_counts(df)
    assert counts["bws_raw_plus9999"] == 1 and counts["bws_score_plus9999"] == 0


def test_normalize_dataframe_nans_score_sentinels_and_counts_raw():
    raw = _aq_table()
    counts = aq.sentinel_counts(raw)
    assert counts["bws_score_minus9999"] == 3 and counts["bws_score_plus9999"] == 1 and counts["rows"] == 9


def test_baseline_meta_is_country_level_annual_and_never_claims_more():
    m = aq.baseline_meta()
    assert m["geography"] == "country" and m["temporal"] == "annual" and m["field"] == "bws_score"
    assert "not water availability" in m["meaning"]
    assert aq.WATER_STRESS_KIND_SCENARIO == "scenario"


def test_missing_file_gives_none_with_reason(tmp_path):
    r = aq.load_country_baseline("India", path=tmp_path / "x.csv")
    assert r.value is None and "not found" in r.meta["reason"]


def test_loader_reads_the_cleaned_file(tmp_path):
    f = tmp_path / "water_stress_aqueduct.csv"
    _aq_table().to_csv(f, index=False)
    assert aq.load_country_baseline("india", path=f).value == pytest.approx(0.6)  # case-insensitive country


MONTH_MAP = {m: f"bws_{m:02d}_score" for m in range(1, 13)}


def _monthly_table():
    d = {"name_0": ["India", "India", "Norway"]}
    for m in range(1, 13):
        d[f"bws_{m:02d}_score"] = [float(m % 5), float(m % 5) + 1, 0.0]
    return pd.DataFrame(d)


def test_monthly_climatology_requires_an_explicit_month_map(tmp_path):
    f = tmp_path / "w.csv"
    _monthly_table().to_csv(f, index=False)
    with pytest.raises(ValueError):
        aq.load_country_baseline("India", path=f, temporal="monthly_climatology")
    with pytest.raises(ValueError):
        aq.load_country_baseline(
            "India", path=f, temporal="monthly_climatology", month_map={1: "bws_01_score"}, month=1
        )
    r = aq.load_country_baseline("India", path=f, temporal="monthly_climatology", month_map=MONTH_MAP, month=3)
    assert r.value is not None and 0.0 <= r.value <= 1.0
    assert r.meta["temporal"] == "monthly_climatology" and r.meta["month_map"][3] == "bws_03_score"
    with pytest.raises(ValueError):
        aq.monthly_climatology(_monthly_table(), "India", {**MONTH_MAP, 3: "no_such_column"})


def test_env_var_selects_temporal_and_rejects_unknown_values(tmp_path, monkeypatch):
    f = tmp_path / "w.csv"
    _aq_table().to_csv(f, index=False)
    monkeypatch.setenv("AQUEDUCT_TEMPORAL", "weekly")
    with pytest.raises(ValueError):
        aq.load_country_baseline("India", path=f)
    monkeypatch.setenv("AQUEDUCT_TEMPORAL", "monthly_climatology")
    with pytest.raises(ValueError):  # selected, but no explicit month map supplied
        aq.load_country_baseline("India", path=f)
    monkeypatch.delenv("AQUEDUCT_TEMPORAL")
    assert aq.load_country_baseline("India", path=f).meta["temporal"] == "annual"


def test_generated_data_records_that_water_stress_is_the_scenario():
    from src.data_generator import generate_sensor_data

    df = generate_sensor_data(days=2, seed=3)
    prov = df.attrs["water_stress_provenance"]
    assert prov["water_stress_kind"] == "scenario" and "scenario" in prov["water_stress"]
    assert prov["baseline_used_as"] in ("unused", "mean level of the synthetic scenario")
    assert "water_stress" in df.columns  # legacy column unchanged


def test_drought_shield_is_triggered_by_the_scenario_never_the_baseline():
    from src.digital_twin import CoolingMode, DigitalTwin

    twin = DigitalTwin(start_time=datetime(2026, 1, 1, 12))
    assert twin.select_cooling_mode(30.0, 0.95) == CoolingMode.CLOSED_LOOP  # high SCENARIO value -> shield
    assert twin.select_cooling_mode(30.0, 0.0) != CoolingMode.CLOSED_LOOP
    # the live loop feeds the scenario variable to the selector; the baseline appears only as a label
    tree = ast.parse((ROOT / "api" / "services" / "live_broadcast_service.py").read_text())
    calls = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "select_cooling_mode"
    ]
    assert calls
    for c in calls:
        names = {getattr(n, "id", getattr(n, "attr", "")) for a in c.args for n in ast.walk(a)}
        assert "water_stress" in names and not any("baseline" in n for n in names)


# --------------------------------------------------------------------------- claim scan
FORBIDDEN = ("real-time", "real time", "current", "site", "availability")
WINDOW = 60  # characters on either side of "water stress"
_WS = re.compile(r"water[ _]stress", re.I)


def _string_constants(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _offences(path: Path, window: int = WINDOW):
    out = []
    for lineno, text in _string_constants(path):
        for m in _WS.finditer(text):
            around = text[max(0, m.start() - window) : m.end() + window].lower()
            around = around.replace("water_stress_kind", "").replace("water_stress_baseline_meta", "")
            for word in FORBIDDEN:
                if word in around:
                    out.append((path.name, lineno, word))
    return out


def test_claim_scan_detector_self_test(tmp_path):
    bad = tmp_path / "b.py"
    bad.write_text(
        'x = "real-time water stress at your site"\ny = "current water stress"\nz = "water stress availability"\n'
    )
    assert {w for _, _, w in _offences(bad)} >= {"real-time", "site", "current", "availability"}
    ok = tmp_path / "ok.py"
    ok.write_text('x = "annual country-level water stress index (scenario)"\n')
    assert _offences(ok) == []


def test_no_api_or_label_text_describes_water_stress_as_realtime_current_site_or_availability():
    files = sorted((ROOT / "api").rglob("*.py")) + [
        ROOT / "src" / "ingestion" / "water_stress_aqueduct.py",
        ROOT / "src" / "data_generator.py",
    ]
    found = [o for f in files for o in _offences(f)]
    assert not found, f"forbidden claim wording next to 'water stress': {found}"
