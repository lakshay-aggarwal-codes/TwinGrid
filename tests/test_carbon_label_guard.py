"""Task 20 (ML-005): carbon is shown as assumed unless a dated real series exists.

Four cases (real & fresh, real & stale, unavailable, flat fallback) each carry source, region, timestamp, unit and
is_real; report text and served UI strings cannot make a carbon claim the label does not support.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src import carbon_label as cl
from src import carbon_provider
from src import run_export as rx
from src.carbon_label import (
    ASSUMED_FALLBACK,
    CARBON_UNIT,
    REAL_FRESH,
    REAL_STALE,
    UNAVAILABLE,
    carbon_label,
    current_carbon_label,
    unsupported_carbon_claims,
)
from src.carbon_provider import fallback_signal, format_carbon_reduction, load_carbon_signal
from tests.test_run_export import make_run

ROOT = Path(__file__).resolve().parents[1]
RETRIEVED = datetime(2026, 9, 1, tzinfo=timezone.utc)
REQUIRED = ("status", "is_real", "source", "region", "timestamp", "unit")


def _install_series(tmp_path, monkeypatch, *, meta: dict | None):
    csv = tmp_path / "carbon_intensity.csv"
    rows = [
        {"timestamp_utc": f"2026-08-01T{h:02d}:00:00Z", "zone": "IN-NO", "carbon_intensity_gco2_per_kwh": 300 + h}
        for h in range(24)
    ]
    pd.DataFrame(rows).to_csv(csv, index=False)
    if meta is not None:
        (tmp_path / carbon_provider.CARBON_META_FILENAME).write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(carbon_provider, "CLEANED_CARBON_PATH", csv)
    carbon_provider.clear_carbon_cache()
    return csv


GOOD_META = {
    "semantic": "average",
    "unit": CARBON_UNIT,
    "source_version": "test-grid-operator-2026-08",
    "license_ref": "test-licence",
    "retrieved_at": RETRIEVED.isoformat(),
}


@pytest.fixture(autouse=True)
def _clear_cache():
    carbon_provider.clear_carbon_cache()
    yield
    carbon_provider.clear_carbon_cache()


def _assert_complete(label):
    for key in REQUIRED:
        assert key in label, key
    assert label["unit"] == CARBON_UNIT
    assert isinstance(label["is_real"], bool)


# ---- the four cases ------------------------------------------------------------------------------------------
def test_real_and_fresh(tmp_path, monkeypatch):
    _install_series(tmp_path, monkeypatch, meta=GOOD_META)
    label = current_carbon_label(now=RETRIEVED + timedelta(days=10))
    _assert_complete(label)
    assert label["status"] == REAL_FRESH and label["is_real"] is True and label["is_fresh"] is True
    assert label["source"] == "test-grid-operator-2026-08"
    assert label["region"] == "IN-NO"
    assert label["timestamp"] == RETRIEVED.isoformat()
    assert "not a live feed" in label["statement"]


def test_real_and_stale(tmp_path, monkeypatch):
    _install_series(tmp_path, monkeypatch, meta=GOOD_META)
    label = current_carbon_label(now=RETRIEVED + timedelta(days=200))
    _assert_complete(label)
    assert label["status"] == REAL_STALE and label["is_real"] is True and label["is_fresh"] is False
    assert "STALE" in label["ui_label"] and "stale" in label["statement"].lower()
    assert label["source"] and label["region"] and label["timestamp"]


def test_stale_window_is_configurable(tmp_path, monkeypatch):
    _install_series(tmp_path, monkeypatch, meta=GOOD_META)
    monkeypatch.setenv(cl.MAX_AGE_ENV, "5")
    assert current_carbon_label(now=RETRIEVED + timedelta(days=10))["status"] == REAL_STALE
    monkeypatch.setenv(cl.MAX_AGE_ENV, "not-a-number")
    assert current_carbon_label(now=RETRIEVED + timedelta(days=10))["status"] == REAL_FRESH  # default 90


def test_unavailable_when_no_signal_or_load_error(monkeypatch):
    label = carbon_label(None)
    _assert_complete(label)
    assert label["status"] == UNAVAILABLE and label["is_real"] is False
    assert label["source"] is None and label["region"] is None and label["timestamp"] is None

    def boom(*a, **k):
        raise OSError("disk unreadable")

    monkeypatch.setattr(cl, "load_carbon_signal", boom)
    assert current_carbon_label()["status"] == UNAVAILABLE


def test_flat_fallback_is_assumed(tmp_path, monkeypatch):
    monkeypatch.setattr(carbon_provider, "CLEANED_CARBON_PATH", tmp_path / "missing.csv")
    label = current_carbon_label()
    _assert_complete(label)
    assert label["status"] == ASSUMED_FALLBACK and label["is_real"] is False
    assert "world-average" in label["source"] and label["region"] == "world average"
    assert label["timestamp"] is None
    assert "Assumed" in label["ui_label"] and "assumed" in label["statement"]


# ---- "real" needs a DATED, documented series -----------------------------------------------------------------
@pytest.mark.parametrize(
    "meta, why",
    [
        (None, "no sidecar at all"),
        ({**GOOD_META, "retrieved_at": None}, "no retrieval date"),
        ({**GOOD_META, "semantic": "whatever"}, "undocumented meaning"),
    ],
)
def test_loaded_but_undated_or_undocumented_series_is_still_assumed(tmp_path, monkeypatch, meta, why):
    _install_series(tmp_path, monkeypatch, meta=meta)
    label = current_carbon_label(now=RETRIEVED + timedelta(days=1))
    assert label["status"] == ASSUMED_FALLBACK and label["is_real"] is False, why
    _assert_complete(label)


def test_future_dated_series_is_not_real(tmp_path, monkeypatch):
    _install_series(tmp_path, monkeypatch, meta=GOOD_META)
    assert current_carbon_label(now=RETRIEVED - timedelta(days=1))["is_real"] is False


def test_series_with_missing_hours_is_assumed(tmp_path, monkeypatch):
    csv = _install_series(tmp_path, monkeypatch, meta=GOOD_META)
    df = pd.read_csv(csv)
    df.iloc[:12].to_csv(csv, index=False)  # only half the day has data
    carbon_provider.clear_carbon_cache()
    assert current_carbon_label(now=RETRIEVED + timedelta(days=1))["is_real"] is False


# ---- claim guard ---------------------------------------------------------------------------------------------
NOT_REAL = [carbon_label(None), carbon_label(fallback_signal())]
REAL = {"is_real": True}


@pytest.mark.parametrize(
    "text",
    [
        "This schedule is carbon-optimal.",
        "The optimizer saves CO2 every night.",
        "Saves carbon by shifting load.",
        "It reduces carbon emissions by 12%.",
        "Annual CO2 savings: 4 t.",
        "Emissions avoided this week.",
        "Carbon-aware optimisation demonstrated.",
        "Based on real grid carbon.",
    ],
)
def test_claim_phrases_are_blocked_when_the_series_is_not_real(text):
    for label in NOT_REAL:
        assert unsupported_carbon_claims(text, label), text
    assert unsupported_carbon_claims(text, REAL) == []  # a real series may carry the (separately evidenced) wording


@pytest.mark.parametrize(
    "text",
    [
        "No carbon reduction is claimed.",
        "This does not show that it saves CO2.",
        "Carbon is assumed, not measured grid data.",
        "Hours of the day with lower carbon intensity in the loaded series.",
    ],
)
def test_negated_or_descriptive_text_is_allowed(text):
    for label in NOT_REAL:
        assert unsupported_carbon_claims(text, label) == [], text


def test_generated_report_text_has_no_unsupported_claim_when_not_real(tmp_path):
    from api.services import esg_report_service as esg

    sig = fallback_signal()
    label = carbon_label(sig)
    section = esg.carbon_report_section({"carbon_data_is_real": False}, label)
    texts = [
        section["value"],
        section["note"],
        section["warning"] or "",
        format_carbon_reduction(sig, 14.0),
        label["statement"],
        label["ui_label"],
    ]
    make_run(tmp_path)  # carbon.is_real False in the fixture run
    texts.append(rx.export_run(tmp_path, "run-a").decode("utf-8"))
    for text in texts:
        assert unsupported_carbon_claims(text, label) == [], text
    assert section["value"] == "ASSUMPTION" and section["warning"]


def test_esg_section_follows_the_label_over_the_legacy_flag():
    from api.services import esg_report_service as esg

    flagged = {"carbon_data_is_real": True, "carbon_intensity_gco2_per_kwh": 120.0}
    assert esg.carbon_report_section(flagged, carbon_label(fallback_signal()))["value"] == "ASSUMPTION"
    assert esg.carbon_report_section(flagged, carbon_label(None))["warning"]
    stale = {
        "status": REAL_STALE, "is_real": True, "is_fresh": False, "source": "s", "region": "r",
        "timestamp": "t", "unit": CARBON_UNIT, "statement": "it is old",
    }  # fmt: skip
    section = esg.carbon_report_section(flagged, stale)
    assert section["value"] == "Loaded series (STALE)" and "STALE" in section["warning"]
    assert "Source: s" in section["note"] and "region: r" in section["note"]


def test_run_export_does_not_present_a_real_flag_as_a_saving(tmp_path):
    from tests.test_run_export import _results

    make_run(tmp_path, results=_results(carbon={"is_real": True, "flat_curve": False}))
    md = rx.export_run(tmp_path, "run-a").decode("utf-8")
    assert "marked real by the run" in md and "no carbon-saving statement" in md
    assert "REAL" not in md.split("## Carbon signal")[1].split("##")[0]


# ---- served UI / API strings -----------------------------------------------------------------------------------
def test_served_sources_contain_no_unsupported_carbon_claim():
    offenders = []
    for base, exts in (("twin-stream-insight-main/src", (".ts", ".tsx")), ("api", (".py",))):
        for p in (ROOT / base).rglob("*"):
            if p.suffix not in exts or ".test." in p.name or "test" in p.name.lower() and "fixture" in p.name.lower():
                continue
            if "fixtures" in p.parts or "node_modules" in p.parts:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                hits = unsupported_carbon_claims(line, NOT_REAL[0])
                if hits:
                    offenders.append(f"{p.relative_to(ROOT)}:{n}: {hits}")
    assert offenders == []


def test_provider_text_never_claims_a_reduction_for_an_assumed_signal():
    assert load_carbon_signal  # imported for the provider contract below
    text = format_carbon_reduction(fallback_signal(), 25.0)
    assert "No carbon reduction is claimed" in text and "25" not in text
