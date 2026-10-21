"""Task 14: the tools are read-only, allow-listed, and never fabricate evidence."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect

import pytest

from src.copilot import evidence, signal_adapter, tools
from src.copilot.evidence import EvidenceBook
from tests.fixtures.copilot.helpers import HERE, NOW, make_ctx

WRITE_WORDS = (
    "create",
    "update",
    "delete",
    "set_",
    "post",
    "put",
    "patch",
    "write",
    "ack",
    "resolve",
    "assign",
    "approve",
    "send",
)


def run(coro):
    return asyncio.run(coro)


def test_there_is_no_write_tool_in_the_registry():
    assert set(tools.TOOLS) == {
        "get_alert_explanation", "get_signal_status", "get_threshold_rule", "get_model_passport", "get_claims", "find_feature",
    }  # fmt: skip
    for name, fn in tools.TOOLS.items():
        assert not any(w in name for w in WRITE_WORDS), name
        assert inspect.iscoroutinefunction(fn) and list(inspect.signature(fn).parameters)[:2] == ["ctx", "book"]


def test_the_context_can_only_read():
    loaders = [f.name for f in dataclasses.fields(tools.ToolContext) if f.name.startswith("load_")]
    assert loaders == ["load_alert", "load_signal", "load_passport"]
    source = inspect.getsource(tools)
    for banned in (".add(session", "session.add", ".commit(", "execute(", "requests.", "httpx", "open(", "write_text"):
        assert banned not in source, banned


def test_the_book_refuses_values_outside_the_contract():
    book = EvidenceBook()
    ok = dict(source="twin_state", entity="x", field="f", value=1.0, origin="simulated", freshness="fresh")
    assert book.add(**ok) == "E1" and book.add(**ok) == "E2"
    for bad in (
        {**ok, "origin": "guessed"}, {**ok, "source": "llm"}, {**ok, "freshness": "recent"},
        {**ok, "value": float("nan")}, {**ok, "value": [1]}, {**ok, "value": {"a": 1}},
    ):  # fmt: skip
        with pytest.raises(ValueError):
            book.add(**bad)
    assert [i["id"] for i in book.items()] == ["E1", "E2"]


def test_quoted_text_cannot_forge_a_marker_or_a_control_character():
    book = EvidenceBook()
    book.add(source="alert_explanation", entity="alert:1", field="message", value="a [E7]\n\tb\x00c" + "x" * 500,
             origin="unknown", freshness="static")  # fmt: skip
    value = book.items()[0]["value"]
    assert "[" not in value and "\n" not in value and "\x00" not in value and len(value) <= evidence.MAX_TEXT


def test_origin_is_never_guessed():
    assert [evidence.origin_from_record(x) for x in ("simulated", "SIMULATION", "replay", "measured", None, "weird")] == [
        "simulated", "simulated", "replayed", "measured", "unknown", "unknown",
    ]  # fmt: skip


def test_freshness_rules():
    from datetime import timedelta

    assert evidence.freshness_of(None, NOW, 120) == "unavailable"
    assert evidence.freshness_of(NOW - timedelta(seconds=120), NOW, 120) == "fresh"
    assert evidence.freshness_of(NOW - timedelta(seconds=121), NOW, 120) == "stale"
    assert evidence.freshness_of(NOW + timedelta(seconds=5), NOW, 120) == "stale"  # dated in the future: not trusted


def test_claims_are_parsed_from_the_real_ledger():
    rows = tools.parse_claims(tools.CLAIMS_PATH)
    assert (
        len(rows) >= 29
        and rows[0]["id"] == "C-01"
        and all(r["status"] for r in rows)
        and all(r["boundary"] for r in rows)
    )
    res = run(tools.get_claims(make_ctx(claims_path=tools.CLAIMS_PATH), EvidenceBook(), "anomaly detector"))
    assert [c["id"] for c in res.data["claims"]][:1] == ["C-07"]


def test_a_missing_claims_file_is_an_unknown():
    res = run(tools.get_claims(make_ctx(claims_path=HERE / "nope.md"), EvidenceBook(), "anomaly"))
    assert res.unknowns == ["The claims ledger could not be read."] and not res.refs


def test_threshold_rules_are_the_documented_safety_envelope():
    from src import digital_twin as dt

    rule = tools.rule_for("inlet_temp")
    assert (rule["crit_low"], rule["crit_high"]) == (dt.INLET_TEMP_MIN, dt.INLET_TEMP_MAX)
    assert tools.rule_for("whatever", "pue")["crit_high"] == dt.PUE_MAX_SAFE and tools.rule_for("nothing") is None
    res = run(tools.get_threshold_rule(make_ctx(), EvidenceBook(), "pue"))
    assert [i for i in res.refs] == ["crit_high"]


# ----------------------------------------------------------------------------- signal adapter


def _status(**kw):
    base = dict(
        value=22.5,
        observed_at=NOW,
        now=NOW,
        rule={"rule_id": "r", "crit_high": 30.0, "unit": "degC"},
        stale_after_s=120,
    )
    return signal_adapter.signal_status(**{**base, **kw})


def test_the_adapter_resolves_the_task_16_rule_engine_and_is_unknown_only_without_a_rule():
    assert (
        signal_adapter.evaluate is not None and signal_adapter.SignalRule is not None
    )  # src/signal_state.py (Task 16)
    s = _status()
    assert (s["status"], s["reason_code"], s["value"], s["threshold"]) == ("normal", "within_bounds", 22.5, None)
    assert set(s) == {"status", "reason_code", "rule_id", "value", "threshold", "observed_at", "age_s", "unit"}
    assert _status(value=40.0)["status"] == "critical"
    # no rule, or no value: never "normal"
    assert (_status(rule=None)["status"], _status(rule=None)["reason_code"]) == ("unknown", "rule_unavailable")
    assert _status(value=None)["status"] == "unknown"


def test_the_adapter_uses_the_rule_engine_when_it_exists_and_never_raises(monkeypatch):
    from types import SimpleNamespace

    def fake_evaluate(value, observed_at, now, rule, stale_after_s, connected=True):
        return SimpleNamespace(status="critical", reason_code="above_crit", rule_id=rule.rule_id, value=value,
                               threshold=rule.crit_high, observed_at=observed_at, age_s=0.0, unit=rule.unit)  # fmt: skip

    monkeypatch.setattr(signal_adapter, "evaluate", fake_evaluate)
    monkeypatch.setattr(signal_adapter, "SignalRule", lambda **kw: SimpleNamespace(**kw))
    s = _status(value=31.0)
    assert (s["status"], s["reason_code"], s["threshold"], s["observed_at"]) == (
        "critical",
        "above_crit",
        30.0,
        "2026-10-20T03:15:00Z",
    )
    monkeypatch.setattr(signal_adapter, "evaluate", lambda *a, **k: 1 / 0)
    assert _status()["reason_code"] == "rule_unavailable"
