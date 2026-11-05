"""Task 5: protocol file, lock, canonicalisation, conflict rules, screening levels. SYNTHETIC fixtures only."""

import itertools
import re
from decimal import Decimal

import numpy as np
import pytest

from research.danish_aau.protocol import lock as lock_mod
from research.danish_aau.protocol.protocol import (
    PROTOCOL_PATH,
    Protocol,
    ProtocolError,
    ProtocolIncomplete,
    load_protocol,
    normalised_bytes,
    protocol_sha256,
)
from research.danish_aau.protocol.rules import (
    RawRow,
    SeriesMeta,
    canonical_text,
    independent_units,
    resolve_group,
    screen_pair,
    to_ticks,
)

SYNTH_RES = {
    "temperature": {"decimals": 2, "basis": "SYNTHETIC TEST"},
    "power": {"decimals": 1, "basis": "SYNTHETIC TEST"},
    "air_speed": {"decimals": 3, "basis": "SYNTHETIC TEST"},
    "surrounding_and_ventilation": {"decimals": 1, "basis": "SYNTHETIC TEST"},
}


@pytest.fixture(scope="module")
def draft() -> Protocol:
    return load_protocol()


@pytest.fixture(scope="module")
def proto(draft) -> Protocol:
    return draft.with_overrides(resolution=SYNTH_RES)


RES = {"A": Decimal("0.01"), "B": Decimal("0.01")}


# ---------------------------------------------------------------------------------------------------------------------
# protocol file and lock
# ---------------------------------------------------------------------------------------------------------------------
def test_committed_protocol_is_an_honest_draft(draft):
    assert draft["status"]["state"] == "draft"
    items = draft.open_items()
    assert any("resolution.temperature.decimals" in i for i in items)
    assert any("approval_ck1" in i for i in items)
    assert draft["time"]["timezone"] == "undeclared"
    assert draft["duplicates"]["authority_fields"] == []


def test_resolution_is_never_guessed(draft):
    with pytest.raises(ProtocolIncomplete):
        draft.resolution("Temperature mod 1 ch 1")


def test_resolution_class_matching(proto):
    assert proto.resolution("Temperature mod 3 ch 4") == Decimal("0.01")
    assert proto.resolution("Power Ch 2") == Decimal("0.1")
    assert proto.resolution("velocity 12") == Decimal("0.001")
    assert proto.resolution("Outdoor_temperature", "AAU_supplementary_surrounding_temperatures.csv") == Decimal("0.1")
    with pytest.raises(ProtocolError):
        proto.resolution("Unknown column")


@pytest.mark.parametrize(
    "mutation,needle",
    [
        ('tie_policy = "missing"', 'tie_policy = "mean"'),
        ('tie_reason = "conflict_unresolved_tie"', 'tie_reason = "picked_first"'),
        ('imputation = "none"', 'imputation = "linear"'),
        ('mode = "ROUND_HALF_EVEN"', 'mode = "ROUND_HALF_UP"'),
        ('cross_cadence = "not_comparable"', 'cross_cadence = "resample"'),
        ('timezone = "undeclared"', 'timezone = "UTC"'),
        ("authority_fields = []", 'authority_fields = [{ name = "file_order", direction = "lower_wins" }]'),
        (
            'merge_dispositions = ["confirmed_duplicate_broadcast", "documented_shared_sensor", "unresolved"]',
            'merge_dispositions = ["confirmed_duplicate_broadcast"]',
        ),
        ("l1_level_correlation = 0.90", "l1_level_correlation = 0.99"),
    ],
)
def test_protocol_rejects_rule_violations(tmp_path, mutation, needle):
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    assert mutation in text
    bad = tmp_path / "p.toml"
    bad.write_text(text.replace(mutation, needle), encoding="utf-8")
    with pytest.raises(ProtocolError):
        load_protocol(bad)


def _lockable_copy(tmp_path):
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    text = text.replace('state = "draft"', 'state = "locked"').replace(
        'approval_ck1 = "pending"', 'approval_ck1 = "approved"'
    )
    text = text.replace('approved_by = ""', 'approved_by = "owner"').replace(
        'approved_on = ""', 'approved_on = "2026-11-06"'
    )
    text = text.replace("task4b_reviewed = false", "task4b_reviewed = true")
    text = text.replace('basis = ""', 'basis = "SYNTHETIC TEST"')
    for name, dec in (("temperature", 2), ("power", 1), ("air_speed", 3), ("surrounding_and_ventilation", 1)):
        text = text.replace(f"[resolution.{name}]\n", f"[resolution.{name}]\ndecimals = {dec}\n")
    p = tmp_path / "protocol_v1.toml"
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def test_lock_refuses_draft_and_open_items(tmp_path):
    with pytest.raises(ProtocolError, match="state"):
        lock_mod.lock(PROTOCOL_PATH, tmp_path / "l.json")
    p = _lockable_copy(tmp_path)
    p.write_text(p.read_text().replace('approval_ck1 = "approved"', 'approval_ck1 = "pending"'), newline="\n")
    with pytest.raises(ProtocolError, match="open items"):
        lock_mod.lock(p, tmp_path / "l.json")


def test_lock_verify_and_tamper_detection(tmp_path):
    p, lk = _lockable_copy(tmp_path), tmp_path / "l.json"
    rec = lock_mod.lock(p, lk)
    assert rec["sha256_lf_normalised"] == protocol_sha256(p)
    assert lock_mod.verify(p, lk) == rec
    p.write_text(p.read_text().replace("l2_diff_correlation = 0.95", "l2_diff_correlation = 0.96"), newline="\n")
    with pytest.raises(ProtocolError, match="changed after locking"):
        lock_mod.verify(p, lk)


def test_hash_is_line_ending_and_bom_independent(tmp_path):
    p = tmp_path / "a.toml"
    data = PROTOCOL_PATH.read_bytes().replace(b"\r\n", b"\n")
    p.write_bytes(b"\xef\xbb\xbf" + data.replace(b"\n", b"\r\n"))
    assert normalised_bytes(p) == data
    assert protocol_sha256(p) == protocol_sha256(PROTOCOL_PATH)


def test_thresholds_come_from_the_file_not_the_code(proto):
    rng = np.random.default_rng(1)
    x = _walk(rng, 2000)
    y = {t: v + 7 for t, v in x.items()}
    a, b = SeriesMeta("a", "f", "a"), SeriesMeta("b", "f", "b")
    assert screen_pair(a, b, x, y, proto).level == 3
    strict = proto.with_overrides(
        screening={"thresholds": {"l3_offset_fraction": 1.5, "l3_equal_fraction": 1.5, "l3_affine_fraction": 1.5}}
    )
    assert screen_pair(a, b, x, y, strict).level < 3


def test_no_numeric_thresholds_hardcoded_in_rules():
    src = (PROTOCOL_PATH.parent / "rules.py").read_text(encoding="utf-8")
    assert not re.search(r"\b0\.9\d*\b", src)


# ---------------------------------------------------------------------------------------------------------------------
# canonicalisation
# ---------------------------------------------------------------------------------------------------------------------
def test_round_half_even_on_text_not_floats():
    r = Decimal("0.01")
    assert to_ticks("0.125", r) == 12 and to_ticks("0.135", r) == 14
    assert to_ticks("2.675", r) == 268  # binary floats would round this down to 2.67
    assert to_ticks("-0.125", r) == -12
    assert canonical_text(268, r) == "2.68" and canonical_text(5, Decimal("1")) == "5"
    with pytest.raises(ProtocolError):
        to_ticks("abc", r)
    with pytest.raises(ProtocolError):
        to_ticks("NaN", r)


# ---------------------------------------------------------------------------------------------------------------------
# duplicate / conflict resolution
# ---------------------------------------------------------------------------------------------------------------------
def rows(*specs):
    return [RawRow(s[0], dict(s[1]), dict(s[2]) if len(s) > 2 else {}) for s in specs]


def test_single_row_is_retained(proto):
    g = resolve_group(rows((5, {"A": "1.234", "B": ""})), RES, proto)
    assert g.group_kind == "single" and g.row_dispositions == {5: "retained"}
    assert g.cells["A"].value == "1.23" and g.cells["B"].observed is False and g.cells["B"].reason is None


def test_exact_duplicates_give_same_value_whichever_row_is_kept(proto):
    base = [(10, {"A": "20.001", "B": "5.000"}), (11, {"A": "20.004", "B": "4.996"})]  # equal at 0.01
    out = set()
    for perm in itertools.permutations(base):
        g = resolve_group(rows(*perm), RES, proto)
        assert g.group_kind == "exact_duplicate"
        assert sorted(g.row_dispositions.values()) == ["exact_duplicate", "retained"]
        out.add((g.cells["A"].value, g.cells["B"].value))
    assert out == {("20.00", "5.00")}
    renumbered = resolve_group(rows((99, base[0][1]), (3, base[1][1])), RES, proto)  # keep-row changes ...
    assert (renumbered.cells["A"].value, renumbered.cells["B"].value) == ("20.00", "5.00")  # ... value does not


def test_shared_timestamp_with_different_values_is_not_a_duplicate(proto):
    g = resolve_group(rows((1, {"A": "20.00", "B": "5.00"}), (2, {"A": "21.00", "B": "6.00"})), RES, proto)
    assert g.group_kind == "conflict"
    assert "exact_duplicate" not in g.row_dispositions.values()


def test_conflict_cell_becomes_missing_never_averaged_or_picked(proto):
    spec = [(1, {"A": "20.00", "B": "5.00"}), (2, {"A": "22.00", "B": "5.00"})]
    for perm in itertools.permutations(spec):
        g = resolve_group(rows(*perm), RES, proto)
        a = g.cells["A"]
        assert (a.observed, a.value, a.reason, a.source_rows) == (False, None, "conflict_unresolved_tie", (1, 2))
        assert g.cells["B"].observed and g.cells["B"].value == "5.00"  # agreeing column is untouched
        assert set(g.row_dispositions.values()) == {"conflict_cell_missing"}


def test_blank_does_not_conflict_with_a_value(proto):
    g = resolve_group(rows((1, {"A": "20.00", "B": ""}), (2, {"A": "", "B": "5.00"})), RES, proto)
    assert g.cells["A"].value == "20.00" and g.cells["B"].value == "5.00"


def test_authority_fields_resolve_only_when_documented_and_strict(proto):
    p = proto.with_overrides(duplicates={"authority_fields": [{"name": "quality_rank", "direction": "lower_wins"}]})
    g = resolve_group(rows((1, {"A": "20.00"}, {"quality_rank": 2}), (2, {"A": "22.00"}, {"quality_rank": 1})), RES, p)
    assert g.cells["A"].value == "22.00" and g.cells["A"].source_rows == (2,)
    assert set(g.row_dispositions.values()) == {"conflict_resolved_by_source_rule"}
    tie = resolve_group(
        rows((1, {"A": "20.00"}, {"quality_rank": 1}), (2, {"A": "22.00"}, {"quality_rank": 1})), RES, p
    )
    assert tie.cells["A"].reason == "conflict_unresolved_tie"  # full tie with different values -> missing
    lacking = resolve_group(rows((1, {"A": "20.00"}, {"quality_rank": 1}), (2, {"A": "22.00"})), RES, p)
    assert lacking.cells["A"].observed is False  # a candidate without the documented field cannot be ranked
    # authority is ignored when the file does not document it (the real CSVs have none)
    none = resolve_group(
        rows((1, {"A": "20.00"}, {"quality_rank": 2}), (2, {"A": "22.00"}, {"quality_rank": 1})), RES, proto
    )
    assert none.cells["A"].observed is False


def test_every_raw_row_gets_exactly_one_disposition(proto):
    allowed = set(proto["dispositions"]["row"])
    for spec in (
        [(1, {"A": "1"})],
        [(1, {"A": "1"}), (2, {"A": "1"}), (3, {"A": "1"})],
        [(1, {"A": "1"}), (2, {"A": "9"})],
    ):
        g = resolve_group(rows(*spec), RES, proto)
        assert set(g.row_dispositions) == {s[0] for s in spec}
        assert set(g.row_dispositions.values()) <= allowed
    with pytest.raises(ProtocolError):
        resolve_group(rows((1, {"A": "1"}), (1, {"A": "1"})), RES, proto)


# ---------------------------------------------------------------------------------------------------------------------
# screening on synthetic series ({naive second: ticks})
# ---------------------------------------------------------------------------------------------------------------------
def _walk(rng, n, step_sd=20.0, start=1000):
    steps = rng.normal(0, step_sd, n).round().astype(int)
    return {t: int(v) for t, v in enumerate(start + np.cumsum(steps))}


A, B = SeriesMeta("a", "f.csv", "A"), SeriesMeta("b", "f.csv", "B")


def test_independent_series_are_not_flagged(proto):
    rng = np.random.default_rng(7)
    r = screen_pair(A, B, _walk(rng, 3000), _walk(rng, 3000), proto)
    assert r.status == "screened" and r.level <= 1, r


def test_equal_offset_and_affine_copies_are_level3(proto):
    rng = np.random.default_rng(8)
    x = _walk(rng, 3000)
    eq = screen_pair(A, B, x, dict(x), proto)
    off = screen_pair(A, B, x, {t: v + 150 for t, v in x.items()}, proto)
    aff = screen_pair(A, B, x, {t: int(round(1.8 * v + 3200)) for t, v in x.items()}, proto)
    assert eq.level == 3 and "equal_at_resolution" in eq.reasons
    assert off.level == 3 and "constant_offset" in off.reasons and "equal_at_resolution" not in off.reasons
    assert aff.level == 3 and "affine_copy" in aff.reasons


def test_shared_driver_is_level1_not_a_copy(proto):
    rng = np.random.default_rng(9)
    driver = np.cumsum(rng.normal(0, 3, 3000)) + 2000
    x = {t: int(round(driver[t] + rng.normal(0, 8))) for t in range(3000)}
    y = {t: int(round(driver[t] * 0.8 + rng.normal(0, 8))) for t in range(3000)}
    r = screen_pair(A, B, x, y, proto)
    assert r.level == 1 and r.reasons == ("level_correlation_shared_driver",), r


def test_lagged_copy_with_noise_is_level2(proto):
    rng = np.random.default_rng(10)
    x = _walk(rng, 3200)
    y = {t: x[t - 5] + int(round(rng.normal(0, 1))) for t in range(5, 3200)}
    r = screen_pair(A, B, x, y, proto)
    assert r.level == 2 and "lagged_difference_correlation" in r.reasons, r
    assert r.stats["best_lag_seconds"] == -5.0 or abs(r.stats["best_lag_seconds"]) == 5.0


def test_shared_gap_pattern_is_level2(proto):
    rng = np.random.default_rng(11)
    gap_starts = [100 * k for k in range(1, 31)]
    dropped = {t + d for t in gap_starts for d in range(1, 6)}  # 5 s holes -> gap events
    x = {t: v for t, v in _walk(rng, 3300).items() if t not in dropped}
    y = {t: v for t, v in _walk(rng, 3300).items() if t not in dropped}
    r = screen_pair(A, B, x, y, proto)
    assert r.level == 2 and "shared_gaps_or_flatlines" in r.reasons, r


def test_same_source_column_or_sensor_id_is_level3_even_without_overlap(proto):
    r = screen_pair(SeriesMeta("a", "f", "C"), SeriesMeta("b", "f", "C"), {1: 1}, {2: 2}, proto)
    assert r.level == 3 and r.status == "insufficient_overlap" and "same_source_column" in r.reasons
    r2 = screen_pair(SeriesMeta("a", "f1", "X", "S9"), SeriesMeta("b", "f2", "Y", "S9"), {1: 1}, {2: 2}, proto)
    assert r2.level == 3 and "same_sensor_id" in r2.reasons


def test_insufficient_overlap_cadence_and_degenerate(proto):
    rng = np.random.default_rng(12)
    x = _walk(rng, 500)
    assert screen_pair(A, B, x, dict(x), proto).status == "insufficient_overlap"
    assert screen_pair(A, B, x, dict(x), proto, cadence_b="10s").status == "not_comparable_cadence"
    flat = {t: 1000 for t in range(3000)}
    r = screen_pair(A, B, flat, dict(flat), proto)
    assert r.status == "degenerate_series" and r.level == 0  # no copy claim from constant series


# ---------------------------------------------------------------------------------------------------------------------
# independent units
# ---------------------------------------------------------------------------------------------------------------------
def test_independent_units_are_conservative(proto):
    ids = ["r1", "r2", "r3", "r4", "r5"]
    disp = {
        ("r1", "r2"): "confirmed_duplicate_broadcast",
        ("r2", "r3"): "unresolved",
        ("r3", "r4"): "independent_shared_driver",
        ("r4", "r5"): "documented_shared_sensor",
    }
    units = independent_units(ids, disp, proto)
    assert units == [["r1", "r2", "r3"], ["r4", "r5"]]
    assert independent_units(ids, {}, proto) == [[i] for i in ids]
    with pytest.raises(ProtocolError):
        independent_units(ids, {("r1", "r2"): "probably_fine"}, proto)
    with pytest.raises(ProtocolError):
        independent_units(ids, {("r1", "zz"): "unresolved"}, proto)
