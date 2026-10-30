"""CP-2: the failover router. No real network: a fake clock drives the unit tests; local fake HTTP servers (the same
``FakeProvider`` Task 24 uses) drive the end-to-end tests through ``llm.enhance``.

Drift check first: if the seams this task assumes are missing, fail loudly instead of testing something else.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest

from src.copilot import answer, llm, providers, router
from tests.fixtures.copilot.helpers import make_ctx
from tests.test_copilot_llm import GOOD, KEY, FakeProvider

pytest_plugins = ["tests.copilot_conftest_plugin"]


@pytest.fixture(autouse=True)
def _fresh_router():
    router.reset()
    yield
    router.reset()


# ----------------------------------------------------------------------------- drift check


def test_assumed_seams_exist():
    for name in ("_call_provider", "validate", "LlmSettings", "enhance", "ProviderError", "Rejected", "load_chain"):
        assert hasattr(llm, name), f"src/copilot/llm.py is missing {name}: CP-1/CP-2 files out of sync"
    for name in ("ProviderConfig", "load_providers", "active_providers", "number"):
        assert hasattr(providers, name), f"src/copilot/providers.py is missing {name}: apply CP-1 first"
    assert hasattr(answer, "answer_question") and hasattr(llm.ProviderError("x"), "status")


# ----------------------------------------------------------------------------- unit tests with a fake clock


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def chain(*names):
    return list(names)


def run(r, names, script, budget=12.0, timeout=10.0, calls=None):
    """``script`` maps provider name -> value to return or an exception to raise (or a callable)."""

    def attempt(name, t):
        if calls is not None:
            calls.append((name, t))
        out = script[name]
        out = out(name, t) if callable(out) else out
        if isinstance(out, BaseException):
            raise out
        return out

    return r.route(names, attempt, name=lambda n: n, key=lambda n: n, timeout=lambda n: timeout, budget_s=budget)


def quota(retry_after=None):
    return router.Failure(router.KIND_QUOTA, "unavailable_http_429", retry_after=retry_after)


def transient(code="unavailable_http_5xx"):
    return router.Failure(router.KIND_TRANSIENT, code)


def rejected(code="rejected_unbacked_number"):
    return router.Failure(router.KIND_REJECTED, code)


def test_first_429_then_second_succeeds():
    r = router.Router(Clock())
    res = run(r, chain("a", "b"), {"a": quota(), "b": "hello"})
    assert res.ok and res.value == "hello" and res.provider == "b"
    assert res.summary() == "a:unavailable_http_429,b:ok"


def test_all_fail_returns_no_value_and_does_not_raise():
    r = router.Router(Clock())
    res = run(r, chain("a", "b"), {"a": quota(), "b": transient()})
    assert not res.ok and res.value is None and not res.rejected


def test_cooldown_skips_a_provider_and_expires():
    clock = Clock()
    r = router.Router(clock)
    calls: list = []
    run(r, chain("a", "b"), {"a": quota(), "b": "x"}, calls=calls)
    calls.clear()
    res = run(r, chain("a", "b"), {"a": "never", "b": "x"}, calls=calls)
    assert [c[0] for c in calls] == ["b"] and res.attempts[0].outcome == "skipped_cooldown"
    clock.advance(router.QUOTA_BASE_S + 1)
    calls.clear()
    res = run(r, chain("a", "b"), {"a": "back", "b": "x"}, calls=calls)
    assert res.provider == "a" and [c[0] for c in calls] == ["a"]


def test_repeated_failures_back_off_longer_and_success_resets():
    clock = Clock()
    r = router.Router(clock)
    script = {"a": transient(), "b": "x"}
    run(r, chain("a", "b"), script)
    assert r.snapshot()["a"]["cooldown_left_s"] == pytest.approx(router.TRANSIENT_BASE_S)
    clock.advance(router.TRANSIENT_BASE_S + 1)
    run(r, chain("a", "b"), script)
    assert r.snapshot()["a"]["failures"] == 2
    assert r.snapshot()["a"]["cooldown_left_s"] == pytest.approx(2 * router.TRANSIENT_BASE_S)
    clock.advance(10_000)
    run(r, chain("a", "b"), {"a": "fine", "b": "x"})
    assert r.snapshot()["a"] == {"failures": 0, "cooldown_left_s": 0.0, "disabled": False}


def test_backoff_is_capped():
    clock = Clock()
    r = router.Router(clock)
    for _ in range(12):
        run(r, chain("a", "b"), {"a": transient(), "b": "x"})
        clock.advance(router.MAX_BACKOFF_S + 1)
    assert r.snapshot()["a"]["cooldown_left_s"] <= 0.0 + 1e-9  # advanced past it
    run(r, chain("a", "b"), {"a": transient(), "b": "x"})
    assert r.snapshot()["a"]["cooldown_left_s"] <= router.MAX_BACKOFF_S


def test_retry_after_is_respected_when_longer_and_capped():
    r = router.Router(Clock())
    run(r, chain("a", "b"), {"a": quota(retry_after=300), "b": "x"})
    assert r.snapshot()["a"]["cooldown_left_s"] == pytest.approx(300)
    r.reset()
    run(r, chain("a", "b"), {"a": quota(retry_after=5), "b": "x"})
    assert r.snapshot()["a"]["cooldown_left_s"] == pytest.approx(router.QUOTA_BASE_S)  # shorter than our floor
    r.reset()
    run(r, chain("a", "b"), {"a": quota(retry_after=10**9), "b": "x"})
    assert r.snapshot()["a"]["cooldown_left_s"] == pytest.approx(router.MAX_RETRY_AFTER_S)
    r.reset()
    run(r, chain("a", "b"), {"a": quota(retry_after=float("nan")), "b": "x"})
    assert r.snapshot()["a"]["cooldown_left_s"] == pytest.approx(router.QUOTA_BASE_S)


def test_auth_failure_disables_for_the_process_and_logs_once(caplog):
    clock = Clock()
    r = router.Router(clock)
    auth = router.Failure(router.KIND_AUTH, "unavailable_http_4xx")
    with caplog.at_level(logging.INFO):
        run(r, chain("a", "b"), {"a": auth, "b": "x"})
        clock.advance(10**6)
        calls: list = []
        res = run(r, chain("a", "b"), {"a": auth, "b": "x"}, calls=calls)
    assert [c[0] for c in calls] == ["b"] and res.attempts[0].outcome == "skipped_disabled"
    assert r.snapshot()["a"]["disabled"] is True
    assert sum("disabled" in rec.getMessage() for rec in caplog.records) == 1


def test_budget_cuts_the_chain_and_clamps_each_attempt():
    clock = Clock()
    r = router.Router(clock)
    calls: list = []

    def slow(name, t):
        clock.advance(t)  # the attempt uses its whole timeout, then times out
        return router.Failure(router.KIND_TRANSIENT, "unavailable_timeout")

    script = {"a": lambda n, t: (_ for _ in ()).throw(slow(n, t)), "b": "x", "c": "x"}
    res = run(r, chain("a", "b", "c"), script, budget=12.0, timeout=10.0, calls=calls)
    assert calls[0] == ("a", 10.0) and calls[1][0] == "b" and calls[1][1] == pytest.approx(2.0)
    assert res.ok and res.provider == "b"
    # now both burn their time: the third never starts
    r.reset()
    calls.clear()
    script = {n: (lambda n, t: (_ for _ in ()).throw(slow(n, t))) for n in "abc"}
    res = run(r, chain("a", "b", "c"), script, budget=12.0, timeout=10.0, calls=calls)
    assert [c[0] for c in calls] == ["a", "b"] and res.budget_exhausted and not res.ok


def test_rejected_answer_tries_the_next_provider_once_then_stops():
    r = router.Router(Clock())
    calls: list = []
    res = run(r, chain("a", "b", "c"), {"a": rejected(), "b": rejected(), "c": "x"}, calls=calls)
    assert [c[0] for c in calls] == ["a", "b"] and not res.ok and res.rejected
    r.reset()
    calls.clear()
    res = run(r, chain("a", "b", "c"), {"a": rejected(), "b": transient(), "c": "x"}, calls=calls)
    assert [c[0] for c in calls] == ["a", "b"] and not res.ok  # the one extra try was used
    r.reset()
    res = run(r, chain("a", "b"), {"a": rejected(), "b": "good"})
    assert res.provider == "b"


def test_a_rejection_is_not_an_availability_failure():
    r = router.Router(Clock())
    run(r, chain("a", "b"), {"a": rejected(), "b": "x"})
    assert r.snapshot().get("a") is None  # no cooldown, no failure count


def test_unexpected_exceptions_never_escape_and_count_as_transient():
    r = router.Router(Clock())
    res = run(r, chain("a", "b"), {"a": RuntimeError("boom SECRET"), "b": "ok"})
    assert res.ok and res.attempts[0].outcome == "unexpected_RuntimeError"
    assert "SECRET" not in res.summary()
    assert r.snapshot()["a"]["failures"] == 1


def test_a_single_provider_chain_keeps_no_state():
    r = router.Router(Clock())
    for _ in range(3):
        res = run(r, chain("a"), {"a": quota(retry_after=300)})
        assert not res.ok and res.attempts[0].outcome == "unavailable_http_429"  # tried every time, never skipped
    assert r.snapshot() == {}


def test_empty_chain_is_a_clean_miss():
    res = run(router.Router(Clock()), [], {})
    assert not res.ok and res.attempts == ()


def test_budget_from_env_is_validated():
    assert router.budget_from_env({}) == router.DEFAULT_BUDGET_S
    assert router.budget_from_env({"COPILOT_LLM_BUDGET_S": "5"}) == 5.0
    for bad in ("banana", "0", "-3", "9999", "nan", ""):
        assert router.budget_from_env({"COPILOT_LLM_BUDGET_S": bad}) == router.DEFAULT_BUDGET_S


# ----------------------------------------------------------------------------- end to end through llm.enhance (fake HTTP)


@pytest.fixture
def servers(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    made: list[FakeProvider] = []

    def make(n: int) -> list[FakeProvider]:
        for _ in range(n):
            made.append(FakeProvider())
        return made

    yield make
    for p in made:
        p.close()


def configure(monkeypatch, provs, names=("alpha", "beta", "gamma"), **extra):
    use = names[: len(provs)]
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", ",".join(use))
    for n, p in zip(use, provs):
        up = n.upper()
        monkeypatch.setenv(f"COPILOT_LLM_{up}_BASE_URL", p.url)
        monkeypatch.setenv(f"COPILOT_LLM_{up}_MODEL", f"model-{n}")
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


def test_e2e_first_429_second_succeeds_then_the_dead_one_is_skipped(servers, monkeypatch):
    a, b = servers(2)
    a.status, a.raw, a.headers = 429, json.dumps({"error": "slow down"}), {"Retry-After": "120"}
    configure(monkeypatch, [a, b])
    r = ask()
    assert r.mode == "llm" and "llm_unavailable" not in r.warnings
    assert len(a.requests) == 1 and len(b.requests) == 1
    cooldown = router.ROUTER.snapshot()[f"alpha|{a.url}|model-alpha"]["cooldown_left_s"]
    assert 100 < cooldown <= 120
    r2 = ask()
    assert r2.mode == "llm" and len(a.requests) == 1 and len(b.requests) == 2  # alpha not asked again


def test_e2e_every_provider_down_is_rule_based_plus_unavailable(servers, monkeypatch):
    a, b = servers(2)
    a.status, b.status = 500, 503
    a.raw = b.raw = json.dumps({"error": "x"})
    configure(monkeypatch, [a, b])
    r = ask()
    base = baseline()
    assert r.mode == "rule_based" and r.answer == base.answer and r.evidence == base.evidence
    assert "llm_unavailable" in r.warnings and r.limits["provider_configured"] is True


def test_e2e_auth_failure_disables_that_provider(servers, monkeypatch):
    a, b = servers(2)
    a.status, a.raw = 401, json.dumps({"error": "bad key"})
    configure(monkeypatch, [a, b])
    assert ask().mode == "llm"
    assert ask().mode == "llm"
    assert len(a.requests) == 1 and len(b.requests) == 2
    assert next(iter(router.ROUTER.snapshot().values()))["disabled"] is True


def test_e2e_a_403_is_also_auth(servers, monkeypatch):
    a, b = servers(2)
    a.status, a.raw = 403, json.dumps({"error": "forbidden"})
    configure(monkeypatch, [a, b])
    ask()
    ask()
    assert len(a.requests) == 1


def test_e2e_other_4xx_is_not_auth(servers, monkeypatch):
    a, b = servers(2)
    a.status, a.raw = 404, json.dumps({"error": "no such model"})
    configure(monkeypatch, [a, b])
    ask()
    assert not any(s["disabled"] for s in router.ROUTER.snapshot().values())


def test_e2e_a_rejected_answer_falls_to_the_next_provider(servers, monkeypatch):
    a, b = servers(2)
    a.content = "Alert 42 scored 99 against a threshold of {{E2}}. The cause is not determined by available evidence."
    configure(monkeypatch, [a, b])
    r = ask()
    assert r.mode == "llm" and len(a.requests) == 1 and len(b.requests) == 1
    assert "llm_rejected" not in r.warnings
    ask()
    assert len(a.requests) == 2  # a rejection is not an outage: alpha is asked again


def test_e2e_two_rejections_stop_the_chain_and_say_rejected(servers, monkeypatch):
    a, b, c = servers(3)
    bad = "Alert 42 scored 99 against a threshold of {{E2}}. The cause is not determined by available evidence."
    a.content = b.content = bad
    configure(monkeypatch, [a, b, c])
    r = ask()
    base = baseline()
    assert r.mode == "rule_based" and r.answer == base.answer and "llm_rejected" in r.warnings
    assert c.requests == []


def test_e2e_budget_cuts_off_a_slow_chain(servers, monkeypatch):
    a, b = servers(2)
    a.delay = 3.0
    configure(monkeypatch, [a, b], COPILOT_LLM_BUDGET_S="1")
    t0 = time.monotonic()
    r = ask()
    took = time.monotonic() - t0
    assert r.mode == "rule_based" and "llm_unavailable" in r.warnings
    assert b.requests == [] and took < 2.9  # alpha's attempt was clamped to the 1 s budget


def test_e2e_chain_summary_is_logged_without_secrets(servers, monkeypatch, caplog):
    a, b = servers(2)
    a.status, a.raw = 429, json.dumps({"error": "SECRET-PROVIDER-BODY"})
    configure(monkeypatch, [a, b])
    with caplog.at_level(logging.DEBUG):
        ask()
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "llm_chain outcome=ok attempts=alpha:unavailable_http_429,beta:ok" in text
    assert (
        [r for r in caplog.records if "copilot_llm" in r.getMessage()][0]
        .getMessage()
        .startswith("copilot_llm provider=")
    )
    for secret in (KEY, "SECRET-PROVIDER-BODY", "BEGIN_DATA", "Authorization", "Why is this alert red"):
        assert secret not in text


def test_e2e_the_keys_do_not_cross_providers(servers, monkeypatch):
    a, b = servers(2)
    a.status, a.raw = 500, json.dumps({"error": "x"})
    configure(monkeypatch, [a, b])
    ask()
    assert a.requests[0]["headers"]["Authorization"] == f"Bearer {KEY}alpha"
    assert b.requests[0]["headers"]["Authorization"] == f"Bearer {KEY}beta"


def test_e2e_nothing_raises_when_a_provider_layer_crashes(monkeypatch):
    def boom(settings, messages):
        raise RuntimeError("provider layer crashed")

    monkeypatch.setattr(llm, "_call_provider", boom)
    for name in ("alpha", "beta"):
        up = name.upper()
        monkeypatch.setenv(f"COPILOT_LLM_{up}_BASE_URL", f"http://{name}.invalid/v1")
        monkeypatch.setenv(f"COPILOT_LLM_{up}_MODEL", "m")
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", "alpha,beta")
    r = ask()
    assert r.mode == "rule_based" and "llm_unavailable" in r.warnings


def test_e2e_one_provider_behaves_as_before(servers, monkeypatch):
    (a,) = servers(1)
    a.status, a.raw = 429, json.dumps({"error": "x"})
    configure(monkeypatch, [a])
    for _ in range(2):
        r = ask()
        assert "llm_unavailable" in r.warnings
    assert len(a.requests) == 2  # no cooldown with a single provider: Task 24 behaviour


def test_retry_after_header_is_parsed_only_when_numeric():
    assert llm._retry_after_seconds("30") == 30.0
    assert llm._retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert llm._retry_after_seconds(None) is None and llm._retry_after_seconds("-5") is None
    assert GOOD  # imported fixture text is the faithful reply the e2e tests rely on
