"""Task 11: carbon is labelled as an assumption everywhere it is shown, and the data-truth docs say so.

No network, no database. The PDF test needs reportlab, a runtime requirement (requirements.txt).
"""

from __future__ import annotations

import re
from pathlib import Path

from api.services import esg_report_service as esg
from src.carbon_provider import FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = ROOT / "twin-stream-insight-main" / "src"


def test_fallback_report_section_says_assumption_never_real():
    section = esg.carbon_report_section({"carbon_data_is_real": False, "carbon_intensity_gco2_per_kwh": 475.0})
    assert section["value"] == "ASSUMPTION"
    assert "Real" not in section["value"]
    assert "475" in section["note"] and "not measured" in section["note"].lower()
    warning = section["warning"]
    assert warning and "ASSUMED, NOT MEASURED" in warning and "475" in warning
    assert "regional" not in warning.lower()  # it is a world-average constant, not a regional figure


def test_missing_flag_or_missing_intensity_is_treated_as_fallback():
    for state in ({}, {"carbon_data_is_real": None}, {"carbon_data_is_real": "yes"}):
        section = esg.carbon_report_section(state)
        assert section["value"] == "ASSUMPTION" and section["warning"], state
    section = esg.carbon_report_section({})
    assert f"{FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH:.0f}" in section["note"]


def test_real_series_section_never_claims_a_live_feed():
    section = esg.carbon_report_section({"carbon_data_is_real": True, "carbon_intensity_gco2_per_kwh": 120.0})
    assert section["warning"] is None
    assert section["value"] != "Real"
    assert "not a live grid feed" in section["note"]


def test_every_report_carries_the_simulated_notice():
    assert "SIMULATED DATA" in esg.SIMULATED_NOTICE
    assert "None of it is a measurement from a real facility" in esg.SIMULATED_NOTICE


def test_esg_pdf_builds_with_the_new_wording(tmp_path):
    state = {
        "pue": 1.4,
        "wue": 0.5,
        "it_power_kw": 300.0,
        "cooling_power_kw": 90.0,
        "water_consumed_L": 1200.0,
        "carbon_data_is_real": False,
        "carbon_intensity_gco2_per_kwh": 475.0,
    }
    out = esg.generate_report(state, tmp_path / "r.pdf")
    assert out.read_bytes().startswith(b"%PDF")


def test_no_surface_calls_the_carbon_signal_real_grid_data_unconditionally():
    offenders = []
    for path in list(FRONTEND_SRC.rglob("*.ts")) + list(FRONTEND_SRC.rglob("*.tsx")):
        if ".test." in path.name:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("Real diurnal average from Electricity Maps", "(real grid data)", "regional-average fallback"):
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT)}: {needle}")
    assert offenders == []
    assert "regional-average" not in (ROOT / "api" / "services" / "esg_report_service.py").read_text(encoding="utf-8")


def test_frontend_fallback_copy_says_assumption():
    checks = {
        "components/SustainabilityTab.tsx": "ASSUMPTION",
        "components/shell/ModeLegend.tsx": "an assumption",
        "components/scenario/ScenarioLibrary.tsx": "flat assumed carbon intensity",
        "components/scenario/PreviewResults.tsx": "flat assumed carbon intensity",
    }
    for rel, needle in checks.items():
        assert needle in (FRONTEND_SRC / rel).read_text(encoding="utf-8"), rel


def test_data_truth_doc_states_the_hard_facts():
    text = (ROOT / "docs" / "model_cards" / "DATA_TRUTH.md").read_text(encoding="utf-8")
    for needle in (
        "475 gCO2/kWh",
        "no code in this repository produces that file",
        "`server_utilisation`",
        "Synthetic",
        "no intensity column",
        "dormant",
        "no carbon-reduction claim",
    ):
        assert needle.lower() in text.lower(), needle
    licences = (ROOT / "docs" / "DATA_LICENSES.md").read_text(encoding="utf-8")
    assert "DATA_TRUTH.md" in licences and "synthetic" in licences
    dictionary = (ROOT / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    assert "Does not exist" in dictionary


def test_the_constant_in_the_docs_matches_the_code():
    assert FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH == 475.0


def test_nsrdb_solar_is_dormant_nothing_in_the_product_reads_it():
    readers = []
    for folder in ("api", "src", "models"):
        for path in (ROOT / folder).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("src/ingestion/"):
                continue
            if re.search(r"solar_nsrdb|nsrdb", path.read_text(encoding="utf-8"), re.IGNORECASE):
                readers.append(rel)
    assert readers == []
    assert "DORMANT" in (ROOT / "src" / "ingestion" / "solar_nsrdb.py").read_text(encoding="utf-8")
