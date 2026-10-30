"""CP-4: free-tier presets and the client-side limiter. No network: a fake clock drives the limiter unit tests and
``FakeProvider`` (Task 24) plays each provider over local HTTP.

Drift check first: if the seams this task assumes are missing, fail loudly instead of testing something else.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace

import pytest

from src.copilot import answer, limiter, llm, local, presets, providers, router
from tests.fixtures.copilot.helpers import make_ctx
from tests.test_copilot_llm import KEY, FakeProvider

pytest_plugins = ["tests.copilot_conftest_plugin"]

EXPECTED_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "github": "https://models.github.ai/inference",
}
EXPECTED_MODELS = {
    "gemini": "gemini-test-model",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "github": "openai/gpt-4.1",
}


@pytest.fixture(autouse=True)
def _fresh_state():
    router.reset()
    local.reset()
    limiter.reset()
    yield
    router.reset()
    local.reset()
    limiter.reset()


# ----------------------------------------------------------------------------- drift check


def test_assumed_seams_exist():
    for name in ("load_chain", "LlmSettings", "enhance", "_call_provider", "_provider_key"):
        assert hasattr(llm, name), f"src/copilot/llm.py is missing {name}: CP-1..CP-3 files out of sync"
    for name in ("ProviderConfig", "load_providers", "active_providers", "llm_enabled"):
        assert hasattr(providers, name), f"src/copilot/providers.py is missing {name}: apply CP-1 first"
    assert hasattr(local, "with_ollama_preset"), "src/copilot/local.py is missing: apply CP-3 first"
    assert hasattr(router, "Failure") and hasattr(router, "KIND_QUOTA")


# ----------------------------------------------------------------------------- presets


def test_preset_table_is_what_the_docs_say():
    assert {n: p.base_url for n, p in presets.PRESETS.items()} == EXPECTED_URLS
    for p in presets.PRESETS.values():
        assert not p.base_url.endswith("/") and p.docs_url.startswith("https://") and p.rpm > 0 and p.rpd > 0


def test_with_presets_not_used_returns_the_input():
    env = {"COPILOT_LLM_PROVIDERS": "ollama,custom"}
    assert presets.with_presets(env) is env
    assert presets.with_presets({}) == {}


def test_with_presets_fills_only_missing_base_urls_and_never_mutates():
    env = {
        "COPILOT_LLM_PROVIDERS": "Groq, openrouter ,github",
        "COPILOT_LLM_OPENROUTER_BASE_URL": "https://proxy.example.invalid/v1",
    }
    out = presets.with_presets(env)
    assert out["COPILOT_LLM_GROQ_BASE_URL"] == EXPECTED_URLS["groq"]
    assert out["COPILOT_LLM_GITHUB_BASE_URL"] == EXPECTED_URLS["github"]
    assert out["COPILOT_LLM_OPENROUTER_BASE_URL"] == "https://proxy.example.invalid/v1"  # the operator's value wins
    assert "COPILOT_LLM_GROQ_BASE_URL" not in env


def test_a_model_is_never_defaulted():
    env = {"COPILOT_LLM_PROVIDERS": "groq"}
    out = presets.with_presets(env)
    assert not any(k.endswith("_MODEL") for k in out)


def test_limits_come_from_the_preset_unless_overridden():
    assert presets.limits_for("groq", {}) == (presets.PRESETS["groq"].rpm, presets.PRESETS["groq"].rpd)
    assert presets.limits_for("groq", {"COPILOT_LLM_GROQ_RPM": "3", "COPILOT_LLM_GROQ_RPD": "40"}) == (3, 40)
    assert presets.limits_for("groq", {"COPILOT_LLM_GROQ_RPM": "0"})[0] == 0  # 0 switches the limit off
    assert presets.limits_for("openrouter", {"COPILOT_LLM_OPENROUTER_RPD": "1000"})[1] == 1000


@pytest.mark.parametrize("raw", ["abc", "-1", "9999999999", "1.5", ""])
def test_bad_limit_values_fall_back_to_the_default(raw):
    assert presets.limits_for("groq", {"COPILOT_LLM_GROQ_RPM": raw})[0] == presets.PRESETS["groq"].rpm


def test_unknown_and_local_providers_have_no_default_limit():
    assert presets.limits_for("ollama", {}) == (0, 0)
    assert presets.limits_for("mine", {}) == (0, 0)
    assert presets.limits_for("mine", {"COPILOT_LLM_MINE_RPM": "7"}) == (7, 0)


@pytest.mark.parametrize("name", sorted(EXPECTED_URLS))
def test_chain_for_each_preset_has_the_official_base_url(monkeypatch, name):
    up = name.upper()
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", name)
    monkeypatch.setenv(f"COPILOT_LLM_{up}_MODEL", EXPECTED_MODELS[name])
    monkeypatch.setenv(f"COPILOT_LLM_{up}_API_KEY", KEY)
    (s,) = llm.load_chain()
    assert s.name == name and s.base_url == EXPECTED_URLS[name] and s.model == EXPECTED_MODELS[name]
    assert s.configured and s.local is False


# ----------------------------------------------------------------------------- request shape per preset (fake HTTP)


@pytest.mark.parametrize("name", sorted(EXPECTED_URLS))
def test_request_shape_is_the_same_openai_call_for_every_preset(monkeypatch, name):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    up = name.upper()
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", name)
    monkeypatch.setenv(f"COPILOT_LLM_{up}_MODEL", EXPECTED_MODELS[name])
    monkeypatch.setenv(f"COPILOT_LLM_{up}_API_KEY", KEY)
    (s,) = llm.load_chain()
    fake = FakeProvider()
    try:
        content, _rid = llm._call_provider(
            replace(s, base_url=fake.url, timeout_s=5.0), [{"role": "user", "content": "x"}]
        )
    finally:
        fake.close()
    (req,) = fake.requests
    assert req["path"] == "/v1/chat/completions"  # <base>/chat/completions, nothing provider-specific
    assert req["headers"]["Authorization"] == f"Bearer {KEY}"
    assert req["body"]["model"] == EXPECTED_MODELS[name]  # ids with / and : pass through untouched
    assert req["body"]["temperature"] == 0 and req["body"]["stream"] is False
    assert not ({"tools", "functions", "tool_choice"} & set(req["body"]))
    assert content


# ----------------------------------------------------------------------------- limiter unit tests (fake clock)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def test_per_minute_exhaustion_and_recovery():
    c = Clock()
    lim = limiter.RateLimiter(c)
    assert [lim.try_acquire("a", 3, 0) for _ in range(3)] == [0.0, 0.0, 0.0]
    wait = lim.try_acquire("a", 3, 0)
    assert 59 < wait <= 60  # the oldest request leaves the window in a minute
    c.advance(wait + 0.01)
    assert lim.try_acquire("a", 3, 0) == 0.0


def test_refused_requests_are_not_recorded():
    c = Clock()
    lim = limiter.RateLimiter(c)
    lim.try_acquire("a", 1, 0)
    for _ in range(5):
        assert lim.try_acquire("a", 1, 0) > 0
    c.advance(61)
    assert lim.try_acquire("a", 1, 0) == 0.0  # five refusals did not extend the wait
    assert lim.snapshot()["a"]["last_minute"] == 1


def test_per_day_exhaustion_and_recovery():
    c = Clock()
    lim = limiter.RateLimiter(c)
    for _ in range(4):
        assert lim.try_acquire("a", 0, 4) == 0.0
        c.advance(61)  # minutes pass, the day does not
    wait = lim.try_acquire("a", 0, 4)
    assert wait > 80_000  # about a day minus what has passed
    c.advance(limiter.DAY_S)
    assert lim.try_acquire("a", 0, 4) == 0.0


def test_the_longer_of_the_two_waits_wins():
    c = Clock()
    lim = limiter.RateLimiter(c)
    for _ in range(2):
        lim.try_acquire("a", 2, 2)
    assert lim.try_acquire("a", 2, 2) > 80_000


def test_keys_are_independent_and_zero_means_unlimited():
    lim = limiter.RateLimiter(Clock())
    assert lim.try_acquire("a", 1, 0) == 0.0 and lim.try_acquire("a", 1, 0) > 0
    assert lim.try_acquire("b", 1, 0) == 0.0
    assert all(lim.try_acquire("free", 0, 0) == 0.0 for _ in range(50))
    assert "free" not in lim.snapshot()


def test_limiter_is_thread_safe_under_contention():
    import threading

    lim = limiter.RateLimiter()
    granted: list[int] = []

    def worker():
        for _ in range(50):
            if lim.try_acquire("k", 40, 0) == 0.0:
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 40  # 400 attempts, never more than the limit let through


# ----------------------------------------------------------------------------- end to end through llm.enhance (fake HTTP)


@pytest.fixture
def servers(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    made: list[FakeProvider] = []

    def make(n):
        for _ in range(n):
            made.append(FakeProvider())
        return made[-n:]

    yield make
    for p in made:
        p.close()


def use(monkeypatch, provs, names, **extra):
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", ",".join(names))
    for n, p in zip(names, provs):
        up = n.upper()
        monkeypatch.setenv(f"COPILOT_LLM_{up}_BASE_URL", p.url)  # the fake server stands in for the preset's host
        monkeypatch.setenv(f"COPILOT_LLM_{up}_MODEL", EXPECTED_MODELS.get(n, "m"))
        monkeypatch.setenv(f"COPILOT_LLM_{up}_API_KEY", KEY + n)
        monkeypatch.setenv(f"COPILOT_LLM_{up}_TIMEOUT_S", "5")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def ask():
    inp = answer.AskInput(question="Why is this alert red?", kind="alert", context_id="42")
    return asyncio.run(answer.answer_question(inp, make_ctx(), llm_settings=None))


def baseline():
    inp = answer.AskInput(question="Why is this alert red?", kind="alert", context_id="42")
    return asyncio.run(answer.answer_question(inp, make_ctx(), llm_settings=llm.LlmSettings()))


def test_e2e_per_minute_limit_stops_before_the_provider_and_the_next_one_answers(servers, monkeypatch):
    groq, other = servers(2)
    use(monkeypatch, [groq, other], ["groq", "custom"], COPILOT_LLM_GROQ_RPM="1")
    assert ask().mode == "llm" and ask().mode == "llm"
    assert len(groq.requests) == 1  # the second question never reached groq
    assert len(other.requests) == 1
    key = next(k for k in router.ROUTER.snapshot() if k.startswith("groq|"))
    assert router.ROUTER.snapshot()[key]["cooldown_left_s"] > 0


def test_e2e_single_provider_over_its_limit_is_rule_based_with_no_request(servers, monkeypatch):
    (groq,) = servers(1)
    use(monkeypatch, [groq], ["groq"], COPILOT_LLM_GROQ_RPM="1")
    assert ask().mode == "llm"
    r = ask()
    base = baseline()
    assert r.mode == "rule_based" and r.answer == base.answer and r.evidence == base.evidence
    assert "llm_unavailable" in r.warnings and len(groq.requests) == 1


def test_e2e_daily_limit_exhaustion(servers, monkeypatch):
    (groq,) = servers(1)
    use(monkeypatch, [groq], ["groq"], COPILOT_LLM_GROQ_RPM="0", COPILOT_LLM_GROQ_RPD="2")
    modes = [ask().mode for _ in range(4)]
    assert modes == ["llm", "llm", "rule_based", "rule_based"] and len(groq.requests) == 2


def test_e2e_limit_zero_switches_the_preset_default_off(servers, monkeypatch):
    (groq,) = servers(1)
    use(monkeypatch, [groq], ["groq"], COPILOT_LLM_GROQ_RPM="0", COPILOT_LLM_GROQ_RPD="0")
    assert all(ask().mode == "llm" for _ in range(3)) and len(groq.requests) == 3


def test_e2e_a_provider_429_still_fails_over_and_counts_against_the_limit(servers, monkeypatch):
    groq, other = servers(2)
    groq.status, groq.raw = 429, json.dumps({"error": "slow down"})
    use(monkeypatch, [groq, other], ["groq", "custom"])
    assert ask().mode == "llm" and len(groq.requests) == 1 and len(other.requests) == 1
    assert (
        limiter.LIMITER.snapshot()[next(k for k in limiter.LIMITER.snapshot() if k.startswith("groq|"))]["last_day"]
        == 1
    )


def test_e2e_openrouter_402_is_not_an_auth_failure(servers, monkeypatch):
    orouter, other = servers(2)
    orouter.status, orouter.raw = 402, json.dumps({"error": {"message": "negative balance"}})
    use(monkeypatch, [orouter, other], ["openrouter", "custom"])
    assert ask().mode == "llm"
    assert not any(s["disabled"] for s in router.ROUTER.snapshot().values())  # backs off, may recover after a top-up


def test_e2e_github_403_missing_scope_disables_that_provider(servers, monkeypatch):
    gh, other = servers(2)
    gh.status, gh.raw = 403, json.dumps({"error": "missing models:read"})
    use(monkeypatch, [gh, other], ["github", "custom"])
    assert ask().mode == "llm" and ask().mode == "llm"
    assert len(gh.requests) == 1  # disabled after the first 403


def test_e2e_cloud_providers_get_no_numbers_and_logs_carry_no_key_or_prompt(servers, monkeypatch, caplog):
    (groq,) = servers(1)
    use(monkeypatch, [groq], ["groq"])
    with caplog.at_level(logging.DEBUG):
        ask()
    sent = json.dumps(groq.requests[0]["body"])
    assert "is_number_use_placeholder" in sent  # numbers are withheld and come back through {{E#}}
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "provider=groq" in text and KEY not in text and "Why is this alert red" not in text
