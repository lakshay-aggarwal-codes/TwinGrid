"""CP-8: who may see which question. No network, no real model, no database.

Covers: the policy settings (local-only, per-intent cloud rule, concurrency limit), the reduced request a cloud provider
is shown, the fail-closed leak check, and the concurrency gate (a slow call is never queued behind another).
The provider is a scripted function that replaces ``llm._call_provider``; the REAL ``answer_question``, router, policy and
``llm.validate`` run around it.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace

import pytest

from src.copilot import answer, docs_answer, limiter, llm, local, policy, router
from tests.fixtures.copilot.helpers import make_ctx

ALERT_TEXT = "Thermal spike on rack row A"
GOOD_ALERT = "Alert 42 scored {{E1}} against a threshold of {{E2}}. The cause is not determined by available evidence."
GOOD_MODEL = "The registry status is {{E1}}."


def cloud(name: str = "cloud-a", **kw) -> llm.LlmSettings:
    base = dict(
        enabled=True, base_url=f"http://{name}.invalid/v1", model=f"{name}-model", api_key="k", timeout_s=2.0, name=name
    )
    return llm.LlmSettings(**{**base, **kw})


def on_machine(name: str = "ollama") -> llm.LlmSettings:
    return cloud(name, local=True, base_url="http://localhost:11434/v1")


class Provider:
    """Replaces ``llm._call_provider``. Records (provider name, messages); answers with ``reply``."""

    def __init__(self, text: str = GOOD_ALERT):
        self.calls: list[tuple[str, list[dict[str, str]]]] = []
        self.text = text
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def __call__(self, settings, messages):
        self.calls.append((settings.name, messages))
        self.started.set()
        if self.block:
            self.release.wait(10)
        return json.dumps({"answer": self.text, "used_evidence": ["E1"]}), "req-1"

    def sent(self, index: int = 0) -> str:
        """What the provider received, as readable text."""
        return json.dumps(self.calls[index][1], ensure_ascii=False)


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    router.reset()
    limiter.reset()
    local.reset()
    policy.GATE.reset()
    for name in (policy.ENV_LOCAL_ONLY, policy.ENV_CLOUD_INTENTS, policy.ENV_MAX_CONCURRENT):
        monkeypatch.delenv(
            name, raising=False
        )  # the suite-wide allow-all fixture is removed: these tests set their own
    monkeypatch.setattr(llm._local, "check", lambda s: local.Health(True, local.REASON_UP))
    yield
    router.reset()
    limiter.reset()
    local.reset()
    policy.GATE.reset()


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr(llm, "_call_provider", p)
    return p


@pytest.fixture
def set_chain(monkeypatch):
    """The route reads the environment chain; here a test hands one in (the environment loader has its own test below)."""

    def _set(chain):
        monkeypatch.setattr(llm, "load_chain", lambda environ=None: list(chain))

    return _set


def ask(settings, question="Why is this alert red?", kind="alert", cid="42", **kw):
    inp = answer.AskInput(question=question, kind=kind, context_id=cid, **kw.pop("inp", {}))
    return asyncio.run(answer.answer_question(inp, make_ctx(**kw), llm_settings=settings))


# ----------------------------------------------------------------------------- settings


def test_the_default_lets_a_cloud_provider_serve_documentation_questions_only():
    assert policy.cloud_intents({}) == ("docs_question",)
    assert policy.cloud_intents({policy.ENV_CLOUD_INTENTS: "   "}) == ("docs_question",)
    assert not policy.local_only({}) and not policy.local_only({policy.ENV_LOCAL_ONLY: "no"})


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("why_red", ("why_red",)),
        ("docs_question, why_red", ("docs_question", "why_red")),
        ("why_red,docs_question", ("docs_question", "why_red")),  # fixed order, so the setting cannot reorder anything
        ("none", ()),
        ("*", policy.CONFIGURABLE_INTENTS),
        ("ALL", policy.CONFIGURABLE_INTENTS),
        ("current_status", ("current_status",)),
        ("bogus, fallback, what_changed", ()),  # unknown or evidence-free intents are ignored, not errors
        ("none,why_red", ("why_red",)),
    ],
)
def test_cloud_intents_setting_is_parsed_without_raising(raw, expected):
    assert policy.cloud_intents({policy.ENV_CLOUD_INTENTS: raw}) == expected


@pytest.mark.parametrize(
    "raw, expected", [(None, 4), ("", 4), ("abc", 4), ("0", 4), ("-3", 4), ("65", 4), ("1", 1), ("64", 64)]
)
def test_max_concurrent_falls_back_to_the_default_on_a_bad_value(raw, expected):
    env = {} if raw is None else {policy.ENV_MAX_CONCURRENT: raw}
    assert policy.max_concurrent(env) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("1", True), ("YES", True), ("on", True), ("false", False), ("maybe", False), ("", False)],
)
def test_local_only_flag_parsing(raw, expected):
    assert policy.local_only({policy.ENV_LOCAL_ONLY: raw}) is expected


# ----------------------------------------------------------------------------- filtering the chain


def test_filter_chain_default_blocks_cloud_for_alert_questions_but_not_documentation_questions():
    chain = [cloud("a"), on_machine("ollama"), cloud("b")]
    docs = policy.filter_chain(chain, "docs_question", {})
    assert [s.name for s in docs.providers] == ["a", "ollama", "b"] and docs.dropped == 0 and docs.reason is None
    alert = policy.filter_chain(chain, "why_red", {})
    assert (
        [s.name for s in alert.providers] == ["ollama"] and alert.dropped == 2 and alert.reason == policy.REASON_INTENT
    )
    assert policy.filter_chain([cloud("a")], "why_red", {}).blocked


def test_filter_chain_local_only_keeps_local_providers_for_every_intent():
    env = {policy.ENV_LOCAL_ONLY: "true", policy.ENV_CLOUD_INTENTS: "*"}  # local-only wins over the intent list
    chain = [cloud("a"), on_machine("ollama")]
    for intent in ("docs_question", "why_red", "model_limits"):
        out = policy.filter_chain(chain, intent, env)
        assert [s.name for s in out.providers] == ["ollama"] and out.reason == policy.REASON_LOCAL_ONLY
    assert policy.filter_chain([cloud("a")], "docs_question", env).blocked


def test_an_unknown_intent_is_treated_as_not_allowed_for_cloud():
    assert policy.filter_chain([cloud("a")], "something_new", {policy.ENV_CLOUD_INTENTS: "*"}).blocked


# ----------------------------------------------------------------------------- end to end: the per-intent rule


def test_default_policy_answers_an_alert_question_rule_based_and_never_calls_a_cloud_provider(provider):
    r = ask(cloud())
    assert provider.calls == [] and r.mode == "rule_based"
    assert "llm_blocked_by_policy" in r.warnings and "llm_unavailable" not in r.warnings
    assert r.limits == {"provider_configured": True}  # a provider exists; this question may not use it
    base = ask(llm.LlmSettings())
    assert (r.answer, r.evidence, r.unknowns, r.links) == (base.answer, base.evidence, base.unknowns, base.links)


def test_default_policy_prefers_the_local_provider_for_an_alert_question(provider, set_chain):
    set_chain([cloud("a"), on_machine("ollama")])
    r = ask(None)
    assert [name for name, _ in provider.calls] == ["ollama"] and r.mode == "llm"


def test_a_local_provider_still_sees_the_full_alert_evidence(provider):
    ask(on_machine())
    sent = provider.sent()
    assert ALERT_TEXT in sent and "alert:42" in sent  # nothing leaves the machine, so nothing is removed


def test_listing_the_intent_lets_a_cloud_provider_serve_it_with_the_reduced_request(provider, monkeypatch):
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "why_red")
    r = ask(cloud())
    assert r.mode == "llm" and len(provider.calls) == 1
    sent = provider.sent()
    assert ALERT_TEXT not in sent and "alert:42" not in sent and "Alert 42" not in sent and "2026-10-20" not in sent


def test_documentation_questions_are_the_one_default_cloud_intent(provider):
    passage = docs_answer.DocsPassage(
        "c1", "docs/runbooks/x.md", "X", "Rotate the signing key and restart the backend.", 9.0, ("rotat",)
    )
    found = docs_answer.DocsResult("ok", "ok", (passage,), 9.0)
    provider.text = "The documentation says: {{E1}}"
    r = ask(cloud(), "What does the runbook say about rotating secrets?", "general", None, docs_search=lambda q: found)
    assert r.intent == "docs_question" and r.mode == "llm" and len(provider.calls) == 1


# ----------------------------------------------------------------------------- end to end: local-only mode


def test_local_only_never_contacts_a_cloud_provider(provider, monkeypatch):
    monkeypatch.setenv(policy.ENV_LOCAL_ONLY, "true")
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "*")
    r = ask(cloud())
    assert provider.calls == [] and "llm_blocked_by_policy" in r.warnings and r.mode == "rule_based"


def test_local_only_uses_the_local_provider_in_a_mixed_chain(provider, monkeypatch, set_chain):
    monkeypatch.setenv(policy.ENV_LOCAL_ONLY, "true")
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "*")
    set_chain([cloud("a"), on_machine("ollama"), cloud("b")])
    r = ask(None)
    assert [name for name, _ in provider.calls] == ["ollama"] and r.mode == "llm"


def test_local_only_from_the_environment_chain(provider, monkeypatch):
    """The route reads the environment: ``COPILOT_LLM_PROVIDERS`` with a local and a cloud provider."""
    for key, value in {
        "COPILOT_LLM_ENABLED": "true", "COPILOT_LLM_PROVIDERS": "groq,ollama",
        "COPILOT_LLM_GROQ_BASE_URL": "https://api.groq.invalid/openai/v1", "COPILOT_LLM_GROQ_MODEL": "g", "COPILOT_LLM_GROQ_API_KEY": "k",
        "COPILOT_LLM_OLLAMA_BASE_URL": "http://localhost:11434/v1", "COPILOT_LLM_OLLAMA_MODEL": "llama-test",
        policy.ENV_LOCAL_ONLY: "true", policy.ENV_CLOUD_INTENTS: "*",
    }.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    r = ask(None)
    assert [name for name, _ in provider.calls] == ["ollama"] and r.mode == "llm"


# ----------------------------------------------------------------------------- the reduced request and the leak check


def _alert_result():
    return ask(llm.LlmSettings())


def test_cloud_view_removes_alert_text_ids_timestamps_and_user_names():
    r = _alert_result()
    view = policy.cloud_view(
        "Why is alert 42 red, asks alice-ops@example.com (alice-ops)?",
        r.answer,
        r.evidence,
        r.unknowns,
        ("alice-ops",),
        r.links,
    )
    text = llm.request_text(view.question, view.draft, view.evidence, view.unknowns, view.links)
    for secret in (ALERT_TEXT, "alert:42", "Alert 42", "alice-ops", "example.com", "2026-10-20", "42"):
        assert secret not in text, secret
    assert not any(e["field"] == "message" for e in view.evidence)
    assert all(
        e["entity"] == "alert" and e["observed_at"] is None for e in view.evidence if e["source"] == "alert_explanation"
    )
    assert [link["path"] for link in view.links] == [
        link["path"] for link in r.links
    ]  # what validate checks is unchanged
    assert policy.leaks(text, view.withheld, r.evidence, user_text=view.user_text, private=view.private) == []


def test_the_local_evidence_is_not_reduced_so_the_validator_still_backs_every_number():
    r = _alert_result()
    before = json.dumps(r.evidence)
    policy.cloud_view("q", r.answer, r.evidence, r.unknowns, ("alice",), r.links)
    assert json.dumps(r.evidence) == before and any(e["field"] == "message" for e in r.evidence)


def test_leaks_names_the_failed_check_and_never_the_value():
    r = _alert_result()
    assert policy.leaks(f"... {ALERT_TEXT} ...", [ALERT_TEXT], r.evidence) == ["withheld_text"]
    assert policy.leaks('"label": "Alert 42"', [], r.evidence) == ["alert_id"]
    assert policy.leaks("", [], r.evidence, user_text="hello Alice", private=["alice"]) == ["user_name"]
    assert (
        policy.leaks("", [], r.evidence, user_text="a malice in wonderland", private=["al", "alice"]) == []
    )  # whole words only
    assert policy.leaks("the admin account", [], r.evidence, private=["admin"]) == []  # a passage may say "admin"


def test_a_question_that_repeats_the_alert_text_blocks_the_cloud_request(provider, monkeypatch):
    """The scrub cannot know the alert text; the leak check does. Fail closed: the provider is never called."""
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "why_red")
    r = ask(cloud(), f"Why is '{ALERT_TEXT}' red?")
    assert provider.calls == [] and "llm_blocked_by_policy" in r.warnings and r.mode == "rule_based"


def test_a_failed_leak_check_still_lets_a_local_provider_answer(provider, monkeypatch, set_chain):
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "why_red")
    set_chain([cloud("a"), on_machine("ollama")])
    r = ask(None, f"Why is '{ALERT_TEXT}' red?")
    assert [name for name, _ in provider.calls] == ["ollama"] and r.mode == "llm"


def test_the_user_name_and_an_address_never_reach_a_cloud_provider(provider, monkeypatch):
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "model_limits")
    provider.text = GOOD_MODEL
    question = "How accurate is the anomaly detector? Asked by alice-ops from 192.168.1.7"
    ask(cloud(), question, "model", "anomaly", inp={"private_terms": ("alice-ops",)})
    assert len(provider.calls) == 1
    sent = provider.sent()
    assert "alice-ops" not in sent and "192.168.1.7" not in sent and "How accurate is the anomaly detector" in sent


# ----------------------------------------------------------------------------- the concurrency gate


def test_gate_counts_and_never_goes_negative():
    gate = policy.ConcurrencyGate()
    assert gate.try_acquire(2) and gate.try_acquire(2) and not gate.try_acquire(2) and gate.active == 2
    gate.release()
    assert gate.try_acquire(2)
    gate.release(), gate.release(), gate.release()
    assert gate.active == 0


def test_a_second_slow_question_is_answered_rule_based_at_once_when_the_limit_is_one(provider, monkeypatch):
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "why_red")
    monkeypatch.setenv(policy.ENV_MAX_CONCURRENT, "1")
    provider.block = True

    async def scenario():
        first = asyncio.create_task(_ask_async(cloud()))
        assert await asyncio.to_thread(provider.started.wait, 5)
        started = time.monotonic()
        second = await _ask_async(cloud())
        elapsed = time.monotonic() - started
        provider.release.set()
        return await first, second, elapsed

    first, second, elapsed = asyncio.run(scenario())
    assert second.mode == "rule_based" and "llm_busy" in second.warnings and elapsed < 1.0
    assert first.mode == "llm" and len(provider.calls) == 1
    assert policy.GATE.active == 0


async def _ask_async(settings):
    inp = answer.AskInput(question="Why is this alert red?", kind="alert", context_id="42")
    return await answer.answer_question(inp, make_ctx(), llm_settings=settings)


def test_the_slot_is_held_until_a_timed_out_call_really_ends(provider, monkeypatch):
    """The client is answered after the wait; the worker thread cannot be cancelled, so it keeps its slot."""
    monkeypatch.setenv(policy.ENV_CLOUD_INTENTS, "why_red")
    provider.block = True

    async def scenario():
        try:
            r = await _ask_async(replace(cloud(), timeout_s=0.1))
            held = policy.GATE.active  # the worker thread is still blocked in the provider
        finally:
            provider.release.set()  # let it end now (asyncio.run waits for worker threads at shutdown)
        deadline = time.monotonic() + 5
        while policy.GATE.active and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        return r, held, policy.GATE.active

    r, held, after = asyncio.run(scenario())
    assert r.mode == "rule_based" and "llm_unavailable" in r.warnings
    assert held == 1 and after == 0
