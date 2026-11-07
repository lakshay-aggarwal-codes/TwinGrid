from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from research.danish_aau.adapter.schema import spec_for_key
from research.danish_aau.cleaning import TIER1_COLUMNS, CleanConfig
from research.danish_aau.mapping import load_mapping
from research.danish_aau.panel import PanelError, build_panel, compare_trees, rerun_check, verify_panel
from research.danish_aau.panel import __main__ as cli
from research.danish_aau.panel.build import (
    DERIVED_FILE,
    REAL_FILE_REFERENCE,
    real_file_reference_differences,
)
from research.danish_aau.panel.channels import check_tier1_against_mapping
from research.danish_aau.protocol.protocol import load_protocol

FILE = "AAU_temperature_and_power_use.csv"
ALL_COLS = sorted(spec_for_key("temperature_power").measurement_columns)


def _ts(sec: int) -> str:
    return f"2000-01-01 {sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def _row(sec: int, **over: str) -> str:
    cells = []
    for j, c in enumerate(ALL_COLS):
        v = (100.0 if c.startswith("Power") else 20.0) + (sec % 7) * 0.5 + j * 0.01
        cells.append(over.get(c, f"{v:.4f}"))
    return ",".join([_ts(sec), *cells])


def write_raw(raw: Path, lines: list[str]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    header = ",".join([spec_for_key("temperature_power").timestamp_column, *ALL_COLS])
    (raw / FILE).write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")


def synth_lines() -> list[str]:
    ln = [_row(s) for s in range(0, 6)]
    ln.append(_row(6, **{"Temperature mod 1 ch 1": "21.305", "Power Ch 1 (W)": "100.05"}))
    ln.append(_row(7, **{"Temperature mod 1 ch 2": ""}))  # blank single, Tier 1
    ln += [_row(8), _row(8, **{"Power Ch 2 (W)": "999.0"})]  # tie in a power channel -> derived undefined
    ln += [_row(9), _row(9)]  # exact duplicate pair
    ln += [_row(10, **{"Temperature mod 2 ch 1": "20.00"}), _row(10, **{"Temperature mod 2 ch 1": "20.50"})]
    ln += [
        _row(11, **{"Temperature mod 3 ch 1": "5.00"}),
        _row(11, **{"Temperature mod 3 ch 1": "6.00"}),
    ]  # outside Tier 1
    ln += [_row(s) for s in range(12, 20)]
    return ln


@pytest.fixture
def raw(tmp_path):
    p = tmp_path / "raw"
    write_raw(p, synth_lines())
    return p


@pytest.fixture
def built(raw, tmp_path):
    out = tmp_path / "panel"
    m = build_panel(raw, out, manifest_path=None)
    return out, m


def test_tier1_columns_equal_the_mapping_tier1_column_set():
    reg = load_mapping()
    ents = check_tier1_against_mapping(reg, load_protocol(), FILE)
    assert [e["source_column"] for e in ents] == list(TIER1_COLUMNS) and len(ents) == 40
    assert sum(e["source_entity_class"] == "rack_probe" for e in ents) == 37
    assert sum(e["source_entity_class"] == "power_channel" for e in ents) == 3


def test_tier1_check_rejects_a_missing_extra_or_misresolved_column():
    reg = load_mapping()
    ents = reg.entities(tier="tier1", load_in_v1=True)

    def stub(items):
        return SimpleNamespace(entities=lambda **kw: items)

    with pytest.raises(PanelError, match="not in the mapping|not in cleaning"):
        check_tier1_against_mapping(stub(ents[:-1]), load_protocol(), FILE)
    extra = dict(ents[0], source_column="Temperature mod 3 ch 1", entity_id="x")
    with pytest.raises(PanelError):
        check_tier1_against_mapping(stub([*ents, extra]), load_protocol(), FILE)
    wrong = [dict(e, resolution_decimals=3) if i == 0 else e for i, e in enumerate(ents)]
    with pytest.raises(PanelError, match="resolution"):
        check_tier1_against_mapping(stub(wrong), load_protocol(), FILE)


def test_build_writes_the_expected_layout_and_verifies(built):
    out, m = built
    for rel in (
        "panel_manifest.json",
        "channels.json",
        DERIVED_FILE,
        "l1/l1_manifest.json",
        "l1/ledger/AAU_temperature_and_power_use.tsv",
    ):
        assert (out / rel).is_file()
    assert len(list((out / "l1" / "observations").glob("*.tsv"))) == 40
    assert verify_panel(out) == [] and verify_panel(out, deep=False) == []
    assert (
        m["visibility"]["redistribution"] == "not_approved" and m["raw"]["verified_against_dataset_manifest"] is False
    )


def test_two_clean_runs_are_byte_identical(raw, tmp_path):
    r = rerun_check(raw, tmp_path / "p", manifest_path=None)
    assert r["identical"] and r["differences"] == [] and r["panel_sha256"] == r["second_panel_sha256"]
    assert not (tmp_path / "p_rerun").exists()
    a, b = tmp_path / "a", tmp_path / "b"
    build_panel(raw, a, manifest_path=None)
    build_panel(raw, b, manifest_path=None, chunksize=3)  # chunking must not change a byte
    assert compare_trees(a, b) == []


def test_raw_rows_reconcile_exactly_with_dispositions(built):
    out, m = built
    led = pd.read_csv(out / "l1/ledger/AAU_temperature_and_power_use.tsv", sep="\t", dtype=str, keep_default_na=False)
    assert len(led) == m["counts"]["raw_rows"] == 24 and led["row_ordinal"].is_unique
    assert led["disposition"].value_counts().to_dict() == {k: v for k, v in m["ledger"]["by_disposition"].items() if v}
    assert sum(m["ledger"]["by_disposition"].values()) == 24 and m["ledger"]["reconciles"] is True
    c = m["counts"]
    assert c["stored_cells"] == 40 * c["unique_seconds"]
    assert c["observed_cells"] == c["stored_cells"] - c["tier1_conflict_missing_cells"] - c["blank_cells"] - 0
    assert c["tier1_conflict_missing_cells"] == 2 and c["tier1_conflict_missing_power"] == 1


def test_derived_total_is_exact_sum_and_never_partial(built):
    out, m = built
    d = pd.read_csv(out / DERIVED_FILE, sep="\t", dtype=str, keep_default_na=False).set_index("ts_text")
    p = {
        i: pd.read_csv(
            out / f"l1/observations/power_ch_{i}_w.tsv", sep="\t", dtype=str, keep_default_na=False
        ).set_index("ts_text")
        for i in (1, 2, 3)
    }
    for ts, row in d.iterrows():
        ins = [p[i].loc[ts] for i in (1, 2, 3)]
        if all(x["state"] == "observed" and x["quality"] == "ok" for x in ins):
            assert row["state"] == "observed" and int(row["value_ticks"]) == sum(int(x["value_ticks"]) for x in ins)
        else:
            assert (
                row["state"] == "missing"
                and row["value_ticks"] == ""
                and row["reason_code"] == "inputs_not_all_observed"
            )
    assert d.loc[_ts(8), "state"] == "missing"  # the power-channel tie
    assert m["outputs"]["derived"]["defined_seconds"] == (d["state"] == "observed").sum()


def test_flagged_input_makes_the_derived_value_absent(raw, tmp_path):
    out = tmp_path / "f"
    build_panel(raw, out, manifest_path=None, config=CleanConfig(range_limits={"power": ("0", "50")}))
    d = pd.read_csv(out / DERIVED_FILE, sep="\t", dtype=str, keep_default_na=False)
    assert (d["state"] == "missing").all()
    assert verify_panel(out) == []


def test_channels_json_records_provenance_quality_and_group_attribution(built):
    out, _ = built
    ch = json.loads((out / "channels.json").read_text())
    meas, der = ch["measured_channels"], ch["derived_channels"]
    assert len(meas) == 40 and {c["provenance"] for c in meas} == {"measured"} and len(der) == 1
    assert der[0]["provenance"] == "derived" and der[0]["split_per_rack"] is False
    assert der[0]["output_member_source_rack_ids"] == ["1", "2", "3", "4", "5", "6"]
    power = [c for c in meas if c["measurand"] == "power"]
    assert len(power) == 3 and all(c["attribution"]["split_allowed"] is False for c in power)
    assert power[0]["attribution"]["scope"] == "rack_group"
    assert all(c["storage_class"] == "research_import_file" and c["mapping"]["mapping_version"] == 1 for c in meas)
    assert all(c["quality"]["stored_seconds"] == 20 for c in meas)


def test_values_trace_to_source_text(raw, built):
    out, _ = built
    obs = pd.read_csv(out / "l1/observations/temperature_mod_1_ch_1.tsv", sep="\t", dtype=str, keep_default_na=False)
    src = pd.read_csv(raw / FILE, dtype=str, keep_default_na=False)
    col = src.columns[0]
    singles = obs[obs["group_size"] == "1"]
    for _, r in singles.iterrows():
        text = src.loc[src[col] == r["ts_text"], "Temperature mod 1 ch 1"].iloc[0]
        assert (
            r["value_ticks"] == str(round(float(text) * 100))
            or abs(int(r["value_ticks"]) - float(text) * 100) <= 0.5001
        )
        assert r["first_row_ordinal"] == str(int(src.index[src[col] == r["ts_text"]][0]) + 1)


def test_manifest_hashes_agree_and_contain_no_local_text(built, raw, tmp_path):
    out, m = built
    l1m = json.loads((out / "l1/l1_manifest.json").read_text())
    assert (
        m["code"]["cleaning_sha256"] == l1m["cleaning_code_sha256"]
        and m["inputs"]["protocol_sha256_lf"] == l1m["protocol_sha256"]
    )
    assert m["raw"]["sha256"] == l1m["source_file_sha256"] and m["time"]["basis"] == "source_text_undeclared_tz"
    for p in out.rglob("*"):
        if p.is_file() and p.name != "run_environment.json":
            text = p.read_text(encoding="utf-8")
            assert str(tmp_path) not in text and "\r" not in text and "UTC" not in text
    assert (out / "run_environment.json").is_file()


def test_verify_detects_tampering(raw, tmp_path):
    for target, edit in (
        (DERIVED_FILE, lambda t: t.replace("\tobserved\tok\t", "\tmissing\tok\t", 1)),
        ("l1/observations/power_ch_1_w.tsv", lambda t: t.replace("\tobserved\t", "\tmissing\t", 1)),
        ("channels.json", lambda t: t.replace('"measured"', '"simulated"', 1)),
        ("panel_manifest.json", lambda t: t.replace('"raw_rows": 24', '"raw_rows": 25')),
    ):
        out = tmp_path / target.replace("/", "_")
        build_panel(raw, out, manifest_path=None)
        p = out / target
        s = p.read_text(encoding="utf-8")
        assert edit(s) != s
        p.write_text(edit(s), encoding="utf-8", newline="\n")
        assert verify_panel(out), target


def test_refusals(raw, tmp_path):
    with pytest.raises(PanelError, match="separate"):
        build_panel(raw, raw / "inside", manifest_path=None)
    out = tmp_path / "o"
    out.mkdir()
    (out / "stale.txt").write_text("x")
    with pytest.raises(PanelError, match="not empty"):
        build_panel(raw, out, manifest_path=None)
    assert sorted(p.name for p in raw.iterdir()) == [FILE]  # raw directory untouched


def test_real_file_reference_comparison():
    assert real_file_reference_differences(dict(REAL_FILE_REFERENCE)) == []
    assert real_file_reference_differences({**REAL_FILE_REFERENCE, "tier1_conflict_missing_cells": 7_690})
    assert (
        REAL_FILE_REFERENCE["stored_cells"] - REAL_FILE_REFERENCE["tier1_conflict_missing_cells"]
        == REAL_FILE_REFERENCE["observed_cells"]
    )


def test_no_simulated_or_synthetic_source_can_enter():
    pkg = Path(__file__).resolve().parents[2] / "panel"
    for p in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            mods = [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            mods += [a.name for a in node.names] if isinstance(node, ast.Import) else []
            assert not any(m.split(".")[0] in {"src", "api"} or "simulat" in m for m in mods), (p.name, mods)


def test_cli_build_verify_and_refusal(raw, tmp_path, capsys):
    out = tmp_path / "c"
    assert cli.main(["build", "--raw", str(raw), "--out", str(out), "--no-manifest"]) == 0
    assert cli.main(["verify", "--out", str(out)]) == 0
    assert cli.main(["build", "--raw", str(raw), "--out", str(out), "--no-manifest"]) == 2  # not empty
    assert "refused" in capsys.readouterr().err
