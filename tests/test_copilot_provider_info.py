"""CP-10: which provider phrased an ``llm`` answer is reported as ``provider`` (name, local, fell_back), and only then.

No network: ``_call_provider`` is replaced by a fake and the chain is set directly. The point is the contract the
frontend badge relies on: a rule-based answer has no provider, an llm answer names exactly one, and nothing but the
name and the data policy (no URL, model id or key) is ever reported.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.copilot import answer, limiter, llm
from src.copilot import local as copilot_local
from src.copilot import router as copilot_router

GOOD = json.dumps({"answer": "The score is {{E1}}.", "used_evidence": ["E1"]})
KEY = "sk-provider-info-secret-0451"


def _result() -> answer.Answer:
    evidence = [
        {
            "id": "E1",
            "source": "threshold_rule",
            "entity": "signal:inlet",
            "field": "score",
            "value": 0.91,
            "unit": None,
            "observed_at": None,
            "origin": "simulated",
            "freshness": "fresh",
        }
    ]
    return answer.Answer(
        answer="The score is [E1].",
        evidence=evidence,
        unknowns=[],
        warnings=[],
        links=[],
        intent="current_status",
    )


def _s(name: str, *, local: bool = False) -> llm.LlmSettings:
    return llm.LlmSettings(
        enabled=True,
        base_url="http://127.0.0.1:9/v1",
        model=f"{name}-model",
        api_key=None if local else KEY,
        timeout_s=2.0,
        name=name,
        local=local,
    )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    copilot_router.reset()
    limiter.reset()
    copilot_local.reset()
    monkeypatch.setattr(llm._local, "check", lambda s, fetch=None: SimpleNamespace(ok=True, reason="ok"))
    yield
    copilot_router.reset()
    limiter.reset()


def _run(chain, behaviour):
    """``behaviour(settings)`` returns the model content or raises ``llm.ProviderError``."""

    def fake(settings, messages):
        return behaviour(settings), "req-1"

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(llm, "load_chain", lambda environ=None: list(chain))
        mp.setattr(llm, "_call_provider", fake)
        return asyncio.run(llm.enhance(_result(), question="what is the score"))
    finally:
        mp.undo()


def test_a_rule_based_answer_has_no_provider():
    assert _result().provider is None
    assert asyncio.run(llm.enhance(_result(), question="q", settings=llm.LlmSettings())).provider is None  # feature off


def test_one_provider_answering_is_named_and_did_not_fall_back():
    r = _run([_s("default")], lambda s: GOOD)
    assert r.mode == "llm"
    assert r.provider == {"name": "default", "local": False, "fell_back": False}


def test_a_local_provider_is_reported_as_local():
    r = _run([_s("ollama", local=True)], lambda s: GOOD)
    assert r.provider == {"name": "ollama", "local": True, "fell_back": False}


def test_failover_to_a_later_provider_is_reported_as_fell_back():
    def behaviour(s):
        if s.name == "groq":
            raise llm.ProviderError("http_429", status=429)
        return GOOD

    r = _run([_s("groq"), _s("ollama", local=True)], behaviour)
    assert r.mode == "llm"
    assert r.provider == {"name": "ollama", "local": True, "fell_back": True}
    assert r.warnings == []  # the answer was phrased: no fallback warning


def test_a_provider_skipped_by_cooldown_still_counts_as_falling_back():
    def behaviour(s):
        if s.name == "groq":
            raise llm.ProviderError("http_503", status=503)
        return GOOD

    chain = [_s("groq"), _s("openrouter")]
    _run(chain, behaviour)  # groq fails, openrouter answers; groq is now cooling down
    r = _run(chain, behaviour)  # second request: groq is skipped, openrouter answers
    assert r.provider == {"name": "openrouter", "local": False, "fell_back": True}


def test_every_provider_failing_gives_no_provider_and_the_rule_based_answer():
    def behaviour(s):
        raise llm.ProviderError("http_500", status=500)

    r = _run([_s("groq"), _s("ollama", local=True)], behaviour)
    assert r.mode == "rule_based" and r.provider is None
    assert "llm_unavailable" in r.warnings
    assert r.answer == _result().answer


def test_a_rejected_answer_gives_no_provider():
    r = _run([_s("default")], lambda s: json.dumps({"answer": "The score is 99.", "used_evidence": ["E1"]}))
    assert r.mode == "rule_based" and r.provider is None
    assert "llm_rejected" in r.warnings


def test_the_provider_block_carries_only_name_local_and_fell_back():
    r = _run([_s("groq")], lambda s: GOOD)
    assert set(r.provider) == {"name", "local", "fell_back"}
    text = json.dumps(r.provider)
    for secret in (KEY, "127.0.0.1", "groq-model", "http"):
        assert secret not in text


def test_a_provider_name_is_reduced_to_safe_characters():
    r = _run([_s("gr oq<script>")], lambda s: GOOD)
    assert r.provider["name"] == "groqscript"
    assert set(r.provider["name"]) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")


def test_the_response_schema_accepts_the_block_and_defaults_to_null():
    from src.copilot.schemas import AskResponse, ProviderInfo

    base = {
        "request_id": "r",
        "mode": "llm",
        "answer": "a",
        "evidence": [],
        "unknowns": [],
        "warnings": [],
        "links": [],
        "limits": {"provider_configured": True},
        "citations": [],
    }
    assert AskResponse(**base).provider is None
    ok = AskResponse(**base, provider={"name": "ollama", "local": True})
    assert ok.provider == ProviderInfo(name="ollama", local=True, fell_back=False)
    with pytest.raises(ValueError):
        AskResponse(**base, provider={"name": "x" * 65, "local": True})
    with pytest.raises(ValueError):
        AskResponse(**base, provider={"name": "ollama"})  # local is required
