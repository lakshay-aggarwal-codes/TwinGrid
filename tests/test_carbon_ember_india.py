"""Ember India monthly data -> staging file -> ``src.carbon_ingest`` -> the provider's label (L-carbon).

All inputs here are small synthetic tables written in the same long format as Ember's release. No real Ember file is
read, so these tests say nothing about Ember's numbers; they check the conversion and, above all, the HONESTY of the label:
monthly values repeated for every hour are real data with a documented source, but they are NOT time-varying.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import carbon_ingest as ci
from src import carbon_provider as cp
from src.carbon_schedule.windows import is_flat

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_carbon_from_ember_india.py"
_spec = importlib.util.spec_from_file_location("make_carbon_from_ember_india", SCRIPT)
mk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mk)

SERIES = ("Power sector emissions", "CO2 intensity", "CO2 intensity", "gCO2/kWh")


def _row(state, date, value, series=SERIES):
    category, sub, variable, unit = series
    return {
        "Country": "India",
        "State": state,
        "Date": date,
        "Category": category,
        "Subcategory": sub,
        "Variable": variable,
        "Unit": unit,
        "Value": value,
    }


def _raw(tmp_path, rows, name="ember.csv"):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _table():
    return [
        _row("Maharashtra", "2025-01-01", "700"),
        _row("Maharashtra", "2025-02-01", "650.5"),
        _row("Maharashtra", "2025-03-01", ""),  # an empty cell is left out, never zero
        _row("Maharashtra", "2024-12-01", "999"),  # another year
        _row("Gujarat", "2025-01-01", "111"),  # another state
        _row("Maharashtra", "2025-01-01", "5", ("Power sector emissions", "CO2 intensity", "Other", "gCO2/kWh")),
        _row("Maharashtra", "2025-01-01", "5", ("Capacity", "Aggregate fuel", "Clean", "MW")),
    ]


META_FIELDS = {"retrieved_at": "2026-10-25T00:00:00+05:30"}


def _load(path):
    cp.clear_carbon_cache()
    return cp.load_carbon_signal(path=path)


# -- reading the table -------------------------------------------------------------------------------------------------


def test_only_the_named_series_state_and_year_are_read_and_empty_cells_are_skipped():
    raw = pd.DataFrame(_table(), dtype=str).fillna("")
    assert mk.monthly_values(raw, "Maharashtra", 2025) == {1: 700.0, 2: 650.5}


def test_an_unknown_state_a_missing_series_a_duplicate_month_and_an_empty_year_are_refused():
    raw = pd.DataFrame(_table(), dtype=str).fillna("")
    with pytest.raises(mk.EmberError, match="not found"):
        mk.monthly_values(raw, "Atlantis", 2025)
    with pytest.raises(mk.EmberError, match="no usable monthly values"):
        mk.monthly_values(raw, "Maharashtra", 2030)
    with pytest.raises(mk.EmberError, match="no rows for the series"):
        mk.monthly_values(raw[raw["Variable"] == "Clean"], "Maharashtra", 2025)
    with pytest.raises(mk.EmberError, match="two values"):
        mk.monthly_values(
            pd.DataFrame([*_table(), _row("Maharashtra", "2025-01-01", "701")], dtype=str).fillna(""),
            "Maharashtra",
            2025,
        )
    with pytest.raises(mk.EmberError, match="lacks columns"):
        mk.monthly_values(pd.DataFrame({"State": ["x"]}), "x", 2025)


# -- expanding to hours ------------------------------------------------------------------------------------------------


def test_each_month_is_repeated_for_every_utc_hour_in_order():
    rows = mk.hourly_rows({1: 700.0, 2: 650.5}, 2025, "Z")
    assert len(rows) == (31 + 28) * 24
    stamps = [datetime.strptime(r["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ") for r in rows]
    assert stamps[0] == datetime(2025, 1, 1) and stamps[-1] == datetime(2025, 2, 28, 23)
    assert all(b - a == timedelta(hours=1) for a, b in zip(stamps, stamps[1:]))
    assert {r["carbon_intensity_gco2_per_kwh"] for r in rows if r["timestamp_utc"] < "2025-02"} == {700.0}
    assert {r["carbon_intensity_gco2_per_kwh"] for r in rows if r["timestamp_utc"] >= "2025-02"} == {650.5}


def test_december_rolls_over_to_the_next_year_without_error():
    rows = mk.hourly_rows({12: 500.0}, 2025, "Z")
    assert len(rows) == 31 * 24 and rows[-1]["timestamp_utc"] == "2025-12-31T23:00:00Z"


# -- end to end: staging -> validated install -> the provider's label ---------------------------------------------------


def _staged_and_installed(tmp_path):
    raw = _raw(tmp_path, _table())
    out = mk.build(raw, tmp_path / "stage", state="Maharashtra", year=2025, **META_FIELDS)
    meta = json.loads(out["meta"].read_text(encoding="utf-8"))
    target = tmp_path / "cleaned" / "carbon_intensity.csv"
    ci.install_carbon_csv(out["csv"], meta, target=target)
    return out, meta, target


def test_the_staging_files_pass_the_existing_validator_and_install(tmp_path):
    out, meta, target = _staged_and_installed(tmp_path)
    assert out["rows"] == (31 + 28) * 24 and out["months"] == [1, 2]
    assert meta["semantic"] == "average" and meta["unit"] == "gCO2/kWh" and meta["resolution_s"] == 3600
    assert "CC-BY-4.0" in meta["license_ref"] and "sha256" in meta["source_version"]
    assert target.exists() and target.with_name(cp.CARBON_META_FILENAME).exists()


def test_a_repeated_monthly_series_is_real_average_data_but_is_not_labelled_time_varying(tmp_path):
    _, _, target = _staged_and_installed(tmp_path)
    sig = _load(target)
    basis = sig.basis()
    assert sig.is_fallback is False and sig.semantic == "average"
    assert "Ember" in (sig.source_version or "") and "CC-BY-4.0" in (sig.license_ref or "")
    assert np.ptp(sig.curve_by_site_local_hour) <= 1e-9 and is_flat(sig.curve_by_site_local_hour)
    assert basis["is_fallback"] is False
    assert basis["time_varying_signal"] is False
    assert "no time-of-day shape" in basis["statement"]


def test_a_series_that_does_vary_through_the_day_is_still_labelled_time_varying(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {
            "timestamp_utc": (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "carbon_intensity_gco2_per_kwh": 300.0 + (h % 24),
            "zone": "Z1",
        }
        for h in range(48)
    ]
    csv = tmp_path / "varying.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    meta = {
        "semantic": "average",
        "unit": "gCO2/kWh",
        "source": "synthetic test fixture",
        "license_ref": "test-only",
        "retrieved_at": "2026-10-01T00:00:00Z",
    }
    target = tmp_path / "out" / "carbon_intensity.csv"
    ci.install_carbon_csv(csv, meta, target=target)
    basis = _load(target).basis()
    assert basis["time_varying_signal"] is True and "no time-of-day shape" not in basis["statement"]


def test_the_fallback_label_is_unchanged(tmp_path):
    basis = _load(tmp_path / "absent.csv").basis()
    assert basis["is_fallback"] is True and basis["time_varying_signal"] is False
    assert "no time-of-day shape" not in basis["statement"]


def test_the_cli_refuses_a_bad_file_with_exit_code_2_and_writes_nothing(tmp_path, capsys):
    raw = _raw(tmp_path, _table())
    code = mk.main(
        [
            "--raw",
            str(raw),
            "--out-dir",
            str(tmp_path / "o"),
            "--state",
            "Atlantis",
            "--retrieved-at",
            "2026-10-25T00:00:00+05:30",
        ]
    )
    assert code == 2 and "refused" in capsys.readouterr().err and not (tmp_path / "o").exists()
