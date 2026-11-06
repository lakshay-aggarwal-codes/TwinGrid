"""Task 6 runner tests. SYNTHETIC data only; the real raw files are never read.

The vectorised runner must agree with the reference implementation in protocol/rules.py.
"""

from __future__ import annotations

import math
import random
from decimal import Decimal

import numpy as np
import pytest

from research.danish_aau.protocol.protocol import load_protocol
from research.danish_aau.protocol.rules import RawRow, SeriesMeta, _events, resolve_group, screen_pair, to_ticks
from research.danish_aau.screening import run_task6_screen as rt

PROTO = load_protocol()
HEADER_COLS = list(rt.REGISTER)


def synthetic_panel(g: int = 4000, seed: int = 7) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """(S, G) ticks/valid with planted equal, offset, affine, lagged-difference copies, gaps and flatlines."""
    rng = np.random.default_rng(seed)
    s = 8
    base = np.cumsum(rng.integers(-3, 4, size=(s, g)), axis=1) + 3000
    t = base.astype(np.int32)
    t[1] = t[0]  # equal copy
    t[2] = t[0] + 17  # constant offset
    t[3] = t[0] * 2 + 5  # affine copy (slope 2)
    t[4, 5:] = t[0, :-5]  # lag 5 copy of series 0
    t[4, :5] = t[4, 5]
    t[5, 200:260] = t[5, 200]  # flatlines in 5 and 6 at the same place
    t[6, 200:260] = t[6, 200]
    t[5, 900:915] = t[5, 900]
    t[6, 900:915] = t[6, 900]
    v = np.ones((s, g), dtype=bool)
    v[:, 1500:1503] = False  # shared gap (3 s)
    v[7, 2500:2600] = False  # a gap only in series 7
    v[3, 3000] = False
    t = np.where(v, t, 0).astype(np.int32)
    cols = HEADER_COLS[:s]
    return t, v, cols


def reference_result(t: np.ndarray, v: np.ndarray, i: int, j: int):
    def series(k: int) -> dict[int, int]:
        return {int(s): int(t[k, s]) for s in np.flatnonzero(v[k])}

    ma = SeriesMeta(f"s{i}", "f.csv", f"c{i}")
    mb = SeriesMeta(f"s{j}", "f.csv", f"c{j}")
    return screen_pair(ma, mb, series(i), series(j), PROTO)


def fast_result(t: np.ndarray, v: np.ndarray, i: int, j: int, cache: dict):
    if "pre" not in cache:
        fam = PROTO.family("power_temperature")
        cache["pre"] = {
            "events": [
                rt.series_events(v[k], t[k], fam["flatline_min_run"], fam["gap_min_step_seconds"])
                for k in range(len(t))
            ],
            "values": [np.unique(t[k][v[k]]) for k in range(len(t))],
        }
        cache["lag"] = rt.lag_correlations(t, v, int(fam["max_lag_seconds"]))
    r_lag, lags = cache["lag"]
    return rt.screen_pair_fast(i, j, t, v, cache["pre"], r_lag, lags, PROTO)


def test_fast_screen_matches_reference_for_every_pair():
    t, v, _ = synthetic_panel()
    cache: dict = {}
    seen_levels = set()
    for i in range(len(t)):
        for j in range(i + 1, len(t)):
            ref = reference_result(t, v, i, j)
            level, status, reasons, stats = fast_result(t, v, i, j, cache)
            assert (level, status, reasons) == (ref.level, ref.status, ref.reasons), (i, j)
            for key, val in ref.stats.items():
                got = stats[key]
                if isinstance(val, float) and math.isnan(val):
                    assert math.isnan(got), (i, j, key)
                else:
                    assert got == pytest.approx(val, rel=1e-9, abs=1e-9), (i, j, key, got, val)
            seen_levels.add(level)
    assert {2, 3} <= seen_levels  # the fixture really exercises copy and suspect levels


def test_events_match_reference():
    t, v, _ = synthetic_panel()
    fam = PROTO.family("power_temperature")
    for k in range(len(t)):
        ref = _events(
            {int(s): int(t[k, s]) for s in np.flatnonzero(v[k])}, fam["flatline_min_run"], fam["gap_min_step_seconds"]
        )
        got = {
            ("gap" if c % 2 == 0 else "flatline", c // 2)
            for c in rt.series_events(v[k], t[k], fam["flatline_min_run"], fam["gap_min_step_seconds"])
        }
        assert got == ref, k


def test_ticks_match_decimal_rounding_including_exact_ties():
    rng = random.Random(3)
    texts = ["21.235", "21.245", "21.225", "-0.005", "0.015", "1130.85", "1130.95", "24.2299995422"]
    texts += [f"{rng.uniform(10, 40):.{rng.randint(3, 10)}f}" for _ in range(3000)]
    texts += [f"{rng.randint(2000, 4000)}.{rng.randint(0, 99):02d}5" for _ in range(500)]  # exact .xx5 ties
    res = Decimal("0.01")
    vals = np.array([[float(x)] for x in texts])
    ticks, finite, amb = rt.ticks_from_floats(vals, np.array([100.0]))
    for k, txt in enumerate(texts):
        got = int(ticks[k, 0]) if not amb[k, 0] else to_ticks(txt, res)
        assert got == to_ticks(txt, res), txt
    assert amb.sum() >= 500


def test_canonicalise_matches_resolve_group_and_is_order_independent():
    cols = ["Temperature mod 1 ch 1", "Temperature mod 1 ch 2", "Power Ch 1 (W)"]
    res = {c: Decimal("0.01") if c.startswith("Temp") else Decimal("0.1") for c in cols}
    texts = [
        {
            "t": 10,
            "r": [("20.001", "21.00", "1000.04"), ("20.004", "21.00", "1000.04")],
        },  # exact duplicate after rounding
        {"t": 11, "r": [("20.00", "21.00", "1000.0"), ("20.50", "21.00", "1000.0")]},  # conflict in col 0
        {"t": 12, "r": [("20.00", "21.00", "1000.0")]},
        {"t": 13, "r": [("1.00", "2.00", "3.0"), ("1.00", "2.30", "3.0"), ("1.00", "2.00", "3.3")]},  # size 3
    ]
    sec, tick, valid, line = [], [], [], 2
    expected = {}
    for g in texts:
        rows = []
        for r in g["r"]:
            rows.append(RawRow(line, dict(zip(cols, r, strict=True))))
            sec.append(g["t"])
            tick.append([to_ticks(x, res[c]) for x, c in zip(r, cols, strict=True)])
            valid.append([True] * 3)
            line += 1
        expected[g["t"]] = resolve_group(rows, res, PROTO)
    sec, tick, valid = np.array(sec), np.array(tick, dtype=np.int32), np.array(valid)
    perm = np.random.default_rng(1).permutation(len(sec))
    for order in (np.arange(len(sec)), perm):
        can = rt.canonicalise(sec[order], tick[order], valid[order], PROTO)
        for n, s in enumerate(can["secs"]):
            ref = expected[int(s)]
            for c, col in enumerate(cols):
                cell = ref.cells[col]
                assert bool(can["valid"][n, c]) == cell.observed
                if cell.observed:
                    assert Decimal(int(can["ticks"][n, c])) * res[col] == Decimal(cell.value)
        led = can["ledger"]
        assert led["rows"] == 8 and led["retained"] + led["exact_duplicate"] + led["conflict_cell_missing"] == 8
        assert led["conflict_cell_missing"] == 5 and led["exact_duplicate"] == 1 and led["retained"] == 2
        assert can["cells_missing"] == 3 and can["group_sizes"] == {2: 2, 3: 1}


def test_read_panel_end_to_end_on_synthetic_csv(tmp_path):
    cols = list(rt.REGISTER)
    rows = [f"{rt.TS_COLUMN}," + ",".join(cols)]
    rng = np.random.default_rng(5)
    for s in range(60):
        ts = f"2024-09-17 09:{s // 60:02d}:{s % 60:02d}"
        vals = ",".join(
            f"{rng.uniform(20, 30):.7f}" if not c.startswith("Power") else f"{rng.uniform(900, 1100):.1f}" for c in cols
        )
        rows.append(f"{ts},{vals}")
    rows.insert(11, rows[10].rsplit(",", 1)[0] + ",23.5000001")  # same timestamp, different last cell
    rows[11] = rows[11].replace(rows[11].split(",")[0], rows[10].split(",")[0], 1)
    p = tmp_path / "AAU_temperature_and_power_use_25_percent_load_period.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    before = p.read_bytes()
    panel = rt.read_panel(p, PROTO, chunk_rows=17)
    assert panel["columns"] == cols and panel["ticks"].shape == (61, 51)
    can = rt.canonicalise(panel["secs"], panel["ticks"], panel["valid"], PROTO)
    assert can["unique_seconds"] == 60 and can["ledger"]["conflict_cell_missing"] == 2
    assert p.read_bytes() == before  # read-only


def test_unexpected_schema_is_rejected(tmp_path):
    p = tmp_path / "AAU_temperature_and_power_use.csv"
    p.write_text(f"{rt.TS_COLUMN},Power Ch 1 (W),Mystery\n2024-09-17 09:00:00,1,2\n", encoding="utf-8")
    with pytest.raises(rt.RunnerError):
        rt.read_panel(p, PROTO)


def test_register_has_all_columns_and_scope():
    assert len(rt.REGISTER) == 51
    classes = [i.cls for i in rt.REGISTER.values()]
    assert (classes.count("P"), classes.count("R"), classes.count("F")) == (3, 37, 11)
    assert (
        rt.pair_kind(rt.REGISTER["Temperature mod 3 ch 1"], rt.REGISTER["Temperature mod 4 ch 1"]) is None
    )  # facility vs facility


def test_refuses_to_write_inside_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    assert rt.main(["--raw", str(raw), "--out-dir", str(raw / "out")]) == 2


def test_main_end_to_end_on_synthetic_raw_folder(tmp_path, monkeypatch, capsys):
    import hashlib
    import json

    import pandas as pd

    cols = list(rt.REGISTER)
    n = 3000
    rng = np.random.default_rng(2)
    base = np.cumsum(rng.normal(0, 0.03, size=(51, n)), axis=1) + rng.uniform(20, 28, size=(51, 1))
    base[4] = base[3]  # planted equal copy of two temperature probes
    ts = pd.date_range("2024-09-17 09:00:00", periods=n, freq="s").strftime("%Y-%m-%d %H:%M:%S")
    d = pd.DataFrame(base.T, columns=cols).round(7)
    d.insert(0, rt.TS_COLUMN, ts)
    raw = tmp_path / "raw"
    raw.mkdir()
    f = raw / "AAU_temperature_and_power_use_25_percent_load_period.csv"
    d.to_csv(f, index=False)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "filename": f.name,
                        "size_bytes": f.stat().st_size,
                        "local_sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(rt, "MANIFEST", manifest)
    assert rt.main(["--raw", str(raw), "--out-dir", str(tmp_path / "out")]) == 0
    text = capsys.readouterr().out
    assert "flagged pairs (Level >= 2): 1 (L3 1)" in text and "sha256 match" in text
    assert (tmp_path / "out" / "task6_screen_output.txt").exists()
    # a changed raw file must abort before any screening
    f.write_bytes(f.read_bytes() + b" ")
    assert rt.main(["--raw", str(raw), "--out-dir", str(tmp_path / "out2")]) == 1
