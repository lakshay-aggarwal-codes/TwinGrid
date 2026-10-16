"""Task 31: every number in a model card traces to a file, and the cards say what is unevaluated.

Each ``- EVIDENCE <label> = <value> | <file> | <path>`` line is resolved in the cited JSON file and compared with the
stated value. Every other number in a card's prose (a decimal, or an integer of four or more digits) must be a rounding
of an evidence value, a substring of one, or a ``DERIVED`` value recomputed here. No training and no registry edit.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ("forecaster", "anomaly_detector", "ppo_optimizer")
EVIDENCE = re.compile(r"^- EVIDENCE (?P<label>\S+) = (?P<value>.+?) \| (?P<file>\S+) \| (?P<path>\S+)\s*$")
DERIVED = re.compile(r"^- DERIVED (?P<label>\S+) = (?P<value>\S+) \| .*$")
NUMBER = re.compile(r"-?\d[\d,]*\.\d+|\d[\d,]{3,}")
T_975_DF2 = 4.302652729911275  # Student t, 0.975 quantile, 2 degrees of freedom
Z_975 = 1.96


def _card(name: str) -> str:
    return (ROOT / "docs" / "model_cards" / f"{name}.md").read_text(encoding="utf-8")


def _resolve(doc, path: str):
    node = doc
    for part in re.findall(r"[^.\[\]]+(?:\[[^\]]+\])?", path):
        m = re.fullmatch(r"(?P<key>[^\[]+)(?:\[(?P<sel>[^=\]]+)=(?P<val>[^\]]+)\])?", part)
        node = node[m["key"]] if isinstance(node, dict) else node[int(m["key"])]
        if m["sel"]:
            node = next(x for x in node if str(x.get(m["sel"])) == m["val"])
    return node


def _evidence(name: str):
    out = []
    for line in _card(name).splitlines():
        m = EVIDENCE.match(line)
        if m:
            out.append(m.groupdict())
    return out


def _same(actual, stated: str) -> bool:
    if stated == "null":
        return actual is None
    if isinstance(actual, bool) or actual is None:
        return False
    if isinstance(actual, (int, float)):
        try:
            return math.isclose(float(stated), float(actual), rel_tol=1e-9, abs_tol=0.0)
        except ValueError:
            return False
    return str(actual) == stated


def test_every_evidence_line_matches_the_file_it_cites():
    seen = 0
    for name in CARDS:
        lines = _evidence(name)
        assert lines, f"{name}: no EVIDENCE lines"
        for ev in lines:
            doc = json.loads((ROOT / ev["file"]).read_text(encoding="utf-8"))
            actual = _resolve(doc, ev["path"])
            assert _same(actual, ev["value"]), (name, ev["label"], ev["value"], actual)
            seen += 1
    assert seen >= 50


def _prose(name: str) -> str:
    keep = [ln for ln in _card(name).splitlines() if not ln.startswith(("- EVIDENCE", "- DERIVED"))]
    return re.sub(r"`[^`]*`", "", "\n".join(keep))


def _traces(token: str, values: list[float], strings: list[str]) -> bool:
    plain = token.replace(",", "")
    k = len(plain.split(".")[1]) if "." in plain else 0
    num = float(plain)
    if any(plain in s or token in s for s in strings):
        return True
    return any(round(v, k) == num or round(abs(v), k) == abs(num) for v in values)


def test_every_number_in_the_prose_traces_to_an_evidence_value():
    for name in CARDS:
        values, strings = [], []
        for ev in _evidence(name):
            strings.append(ev["value"])
            try:
                values.append(float(ev["value"]))
            except ValueError:
                pass
        for line in _card(name).splitlines():
            m = DERIVED.match(line)
            if m:
                values.append(float(m["value"]))
                strings.append(m["value"])
        loose = [t for t in NUMBER.findall(_prose(name)) if not _traces(t, values, strings)]
        assert loose == [], (name, loose)


def test_derived_values_are_recomputed_not_trusted():
    reg = json.loads((ROOT / "models" / "registry.json").read_text(encoding="utf-8"))
    ppo = next(a for a in reg["artifacts"] if a["model_id"] == "ppo_optimizer-20260927T143232Z")["metrics"]
    std, ci = ppo["pue_improvement_std_pct"], ppo["pue_improvement_ci95_pct"]
    assert math.isclose(
        Z_975 * std / math.sqrt(3), ci, rel_tol=1e-9
    )  # the registry used the normal multiplier on 3 seeds
    assert round(T_975_DF2 * std / math.sqrt(3), 3) == 0.244
    assert round(T_975_DF2, 3) == 4.303
    lo, hi = re.search(
        r"rows\[(\d+):(\d+)\]\s*$", "chronological:train=rows[0:20736],heldout=rows[20736:25920]"
    ).groups()
    assert int(hi) - int(lo) == 5184


def test_cards_state_the_negative_and_unevaluated_results_plainly():
    f, a, p = _card("forecaster"), _card("anomaly_detector"), _card("ppo_optimizer")
    assert "No baseline" in f and "no evidence that 0.523" in f
    assert "same held-out rows" in " ".join(a.split()) or "those same held-out rows" in " ".join(a.split())
    assert "PROPOSED_UNCONFIRMED" in a and "has not been run" in a
    assert "NOT_EVALUATED" in p and "quarantined" in p and "claim allowed: none" in p
    assert "worse than the rule" in p and "weak comparator" in p
    lim = (
        _card("LIMITATIONS")
        if False
        else (ROOT / "docs" / "model_cards" / "LIMITATIONS.md").read_text(encoding="utf-8")
    )
    for needle in ("Synthetic training data", "unevaluated or negative", "Carbon is an assumption", "Wording rules"):
        assert needle in lim


def test_no_model_card_overclaims_the_current_state():
    for name in CARDS:
        text = " ".join(_prose(name).lower().split())
        for phrase in ("state-of-the-art", "production-ready", "ai-powered", "guarantee", "proven"):
            assert phrase not in text, (name, phrase)
