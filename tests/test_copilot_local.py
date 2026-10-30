"""CP-3: local Llama (Ollama). No real network and no real Ollama: a fake Ollama (``/api/tags`` plus the OpenAI-style
``/v1/chat/completions``) runs on 127.0.0.1; ``FakeProvider`` from Task 24 plays the cloud provider.

Drift check first: if the seams this task assumes are missing, fail loudly instead of testing something else.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.copilot import answer, llm, local, providers, router
from tests.copilot_conftest_plugin import live_llm
from tests.fixtures.copilot.helpers import make_ctx
from tests.test_copilot_llm import GOOD, KEY, FakeProvider

pytest_plugins = ["tests.copilot_conftest_plugin"]


@pytest.fixture(autouse=True)
def _fresh_state():
    router.reset()
    local.reset()
    yield
    router.reset()
    local.reset()


# ----------------------------------------------------------------------------- drift check


def test_assumed_seams_exist():
    for name in ("load_chain", "load_settings", "LlmSettings", "enhance", "_call_provider", "DEFAULT_TIMEOUT_S"):
        assert hasattr(llm, name), f"src/copilot/llm.py is missing {name}: CP-1/CP-2 files out of sync"
    for name in ("ProviderConfig", "load_providers", "active_providers", "llm_enabled", "DEFAULT_TIMEOUT_S"):
        assert hasattr(providers, name), f"src/copilot/providers.py is missing {name}: apply CP-1 first"
    for name in ("ROUTER", "Failure", "KIND_TRANSIENT", "reset"):
        assert hasattr(router, name), f"src/copilot/router.py is missing {name}: apply CP-2 first"
    assert "local" in llm.LlmSettings.__dataclass_fields__, "LlmSettings lost its `local` flag (CP-1)"


# ----------------------------------------------------------------------------- fake Ollama


class FakeOllama:
    """``GET /api/tags`` lists ``models``; ``POST /v1/chat/completions`` answers like FakeProvider. Requests are logged."""

    def __init__(self, models=("llama-test:latest",), tags_status=200):
        self.models = list(models)
        self.tags_status = tags_status
        self.tags_requests = 0
        self.chat_requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, payload):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    outer.tags_requests += 1
                    self._send(outer.tags_status, {"models": [{"name": m} for m in outer.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.chat_requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
                inner = json.dumps({"answer": GOOD, "used_evidence": ["E1", "E2"]})
                self._send(
                    200, {"id": "chatcmpl-local1", "choices": [{"message": {"role": "assistant", "content": inner}}]}
                )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    made: list[FakeOllama] = []

    def make(**kw) -> FakeOllama:
        made.append(FakeOllama(**kw))
        return made[-1]

    yield make
    for o in made:
        o.close()


def closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"  # nothing listens here any more


def ask():
    inp = answer.AskInput(question="Why is this alert red?", kind="alert", context_id="42")
    return asyncio.run(answer.answer_question(inp, make_ctx(), llm_settings=None))


def baseline():
    inp = answer.AskInput(question="Why is this alert red?", kind="alert", context_id="42")
    return asyncio.run(answer.answer_question(inp, make_ctx(), llm_settings=llm.LlmSettings()))


# ----------------------------------------------------------------------------- unit: preset, urls, numbers


def test_ollama_root_strips_the_version_path():
    assert local.ollama_root("http://localhost:11434/v1") == "http://localhost:11434"
    assert local.ollama_root("http://localhost:11434/v1/") == "http://localhost:11434"
    assert local.ollama_root("http://host.docker.internal:11434") == "http://host.docker.internal:11434"


def test_model_listed_matches_latest_but_not_other_tags():
    names = ["llama3.2:latest", "qwen2.5:7b"]
    assert local.model_listed("llama3.2", names) and local.model_listed("llama3.2:latest", names)
    assert local.model_listed("qwen2.5:7b", names)
    assert not local.model_listed("qwen2.5", names)  # only a 7b tag is installed, no :latest
    assert not local.model_listed("llama3.2:1b", names) and not local.model_listed("", names)


def test_preset_not_used_returns_the_input_untouched():
    env = {"COPILOT_LLM_PROVIDERS": "groq", "COPILOT_LLM_GROQ_BASE_URL": "https://example.invalid/v1"}
    assert local.with_ollama_preset(env) is env
    assert local.with_ollama_preset({}) == {}


def test_preset_fills_base_url_and_local_flag_without_touching_the_input():
    env = {"COPILOT_LLM_PROVIDERS": "ollama", "COPILOT_LLM_OLLAMA_MODEL": "llama3.2"}
    out = local.with_ollama_preset(env)
    assert out["COPILOT_LLM_OLLAMA_BASE_URL"] == "http://localhost:11434/v1"
    assert out["COPILOT_LLM_OLLAMA_LOCAL"] == "true"
    assert "COPILOT_LLM_OLLAMA_BASE_URL" not in env  # input unchanged


def test_preset_keeps_what_the_operator_set():
    env = {
        "COPILOT_LLM_PROVIDERS": "groq, Ollama",
        "COPILOT_LLM_OLLAMA_BASE_URL": "http://host.docker.internal:11434/v1",
        "COPILOT_LLM_OLLAMA_LOCAL": "false",
    }
    out = local.with_ollama_preset(env)
    assert out["COPILOT_LLM_OLLAMA_BASE_URL"] == "http://host.docker.internal:11434/v1"
    assert out["COPILOT_LLM_OLLAMA_LOCAL"] == "false"


def test_a_remote_ollama_host_is_not_flagged_local_by_default():
    env = {"COPILOT_LLM_PROVIDERS": "ollama", "COPILOT_LLM_OLLAMA_BASE_URL": "http://gpu-box.example.invalid:11434/v1"}
    assert "COPILOT_LLM_OLLAMA_LOCAL" not in local.with_ollama_preset(env)


def test_docker_host_and_compose_service_count_as_this_machine():
    assert local.is_local_host("http://host.docker.internal:11434/v1")
    assert local.is_local_host("http://ollama:11434/v1")
    assert not local.is_local_host("https://api.example.invalid/v1") and not local.is_local_host("not a url")


@pytest.mark.parametrize(
    "raw,expected", [(None, 30.0), ("", 30.0), ("abc", 30.0), ("0", 30.0), ("999", 30.0), ("nan", 30.0), ("45", 45.0)]
)
def test_local_timeout_bad_values_fall_back(raw, expected):
    env = {} if raw is None else {"COPILOT_LLM_LOCAL_TIMEOUT_S": raw}
    assert local.local_timeout_s(env) == expected


def test_prepare_lengthens_only_a_local_provider_on_the_default_timeout():
    dflt = llm.DEFAULT_TIMEOUT_S
    cloud = llm.LlmSettings(enabled=True, base_url="u", model="m", timeout_s=dflt)
    mine = llm.LlmSettings(enabled=True, base_url="u", model="m", timeout_s=dflt, local=True)
    custom = llm.LlmSettings(enabled=True, base_url="u", model="m", timeout_s=7.0, local=True)
    assert local.prepare(cloud, {}, dflt) is cloud
    assert local.prepare(mine, {}, dflt).timeout_s == 30.0
    assert local.prepare(mine, {"COPILOT_LLM_LOCAL_TIMEOUT_S": "60"}, dflt).timeout_s == 60.0
    assert local.prepare(custom, {}, dflt) is custom


# ----------------------------------------------------------------------------- unit: health check with a fake fetch


def fetcher(responses, calls=None):
    def fetch(url, timeout):
        if calls is not None:
            calls.append((url, timeout))
        out = responses[url]
        if isinstance(out, BaseException):
            raise out
        return out

    return fetch


def tags(*names):
    return 200, json.dumps({"models": [{"name": n} for n in names]}).encode()


BASE = "http://localhost:11434/v1"
TAGS = "http://localhost:11434/api/tags"


def test_health_up_when_model_is_listed():
    h = local.check(llm.LlmSettings(base_url=BASE, model="llama3.2"), fetcher({TAGS: tags("llama3.2:latest")}))
    assert h == local.Health(True, "up")


def test_health_model_missing_is_its_own_reason():
    h = local.check(llm.LlmSettings(base_url=BASE, model="llama3.2"), fetcher({TAGS: tags("qwen2.5:7b")}))
    assert h == local.Health(False, "local_model_missing")


def test_health_down_on_connection_error_and_uses_a_short_timeout():
    calls: list = []
    h = local.check(llm.LlmSettings(base_url=BASE, model="m"), fetcher({TAGS: ConnectionRefusedError()}, calls))
    assert h == local.Health(False, "local_down")
    assert calls[0][1] <= 1.0


@pytest.mark.parametrize("response", [(500, b"x"), (200, b"not json"), (200, b'{"models": 3}'), (200, b'{"nope": []}')])
def test_health_bad_responses_are_down_not_exceptions(response):
    h = local.check(llm.LlmSettings(base_url=BASE, model="m"), fetcher({TAGS: response}))
    assert not h.ok and h.reason == "local_bad_response"


def test_server_without_api_tags_is_checked_through_v1_models():
    calls: list = []
    ok = fetcher({TAGS: (404, b""), BASE + "/models": (200, b'{"data": []}')}, calls)
    assert local.check(llm.LlmSettings(base_url=BASE, model="m"), ok) == local.Health(True, "up")
    assert [c[0] for c in calls] == [TAGS, BASE + "/models"]
    local.reset()
    bad = fetcher({TAGS: (404, b""), BASE + "/models": (404, b"")})
    assert local.check(llm.LlmSettings(base_url=BASE, model="m"), bad).reason == "local_bad_response"


def test_health_is_cached_and_expires():
    clock = [1000.0]
    cache = local.HealthCache(lambda: clock[0])
    calls: list = []
    f = fetcher({TAGS: ConnectionRefusedError()}, calls)
    assert not cache.check(BASE, "m", f).ok
    assert not cache.check(BASE, "m", f).ok
    assert len(calls) == 1  # second answer came from the cache
    clock[0] += local.DOWN_TTL_S + 1
    cache.check(BASE, "m", f)
    assert len(calls) == 2
    up = local.HealthCache(lambda: clock[0])
    calls.clear()
    f2 = fetcher({TAGS: tags("m:latest")}, calls)
    up.check(BASE, "m", f2)
    clock[0] += local.DOWN_TTL_S + 1  # "up" lives longer than "down"
    up.check(BASE, "m", f2)
    assert len(calls) == 1
    clock[0] += local.UP_TTL_S
    up.check(BASE, "m", f2)
    assert len(calls) == 2


def test_check_never_raises_even_on_garbage_settings():
    assert local.check(object()) == local.Health(False, "local_down")


# ----------------------------------------------------------------------------- end to end through llm.enhance


def use_ollama(monkeypatch, url, model="llama-test", names="ollama", **extra):
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", names)
    if url is not None:
        monkeypatch.setenv("COPILOT_LLM_OLLAMA_BASE_URL", url)
    monkeypatch.setenv("COPILOT_LLM_OLLAMA_MODEL", model)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_e2e_local_ollama_answers_with_no_key_and_is_probed_once(ollama, monkeypatch):
    o = ollama()
    use_ollama(monkeypatch, o.url)
    r1, r2 = ask(), ask()
    assert r1.mode == "llm" and r2.mode == "llm" and "llm_unavailable" not in r1.warnings
    assert len(o.chat_requests) == 2 and o.tags_requests == 1  # second question reused the health result
    sent = o.chat_requests[0]
    assert sent["path"] == "/v1/chat/completions" and sent["body"]["model"] == "llama-test"
    assert "Authorization" not in sent["headers"]  # a local server needs no key
    assert "tools" not in sent["body"]


def test_e2e_the_preset_flags_a_loopback_ollama_as_local(monkeypatch):
    use_ollama(monkeypatch, "http://127.0.0.1:9/v1")
    (s,) = llm.load_chain()
    assert (
        s.name == "ollama" and s.local is True and s.timeout_s == llm.DEFAULT_TIMEOUT_S
    )  # lengthened later, in enhance


def test_e2e_the_preset_supplies_the_default_base_url(monkeypatch):
    use_ollama(monkeypatch, None)
    (s,) = llm.load_chain()
    assert s.base_url == "http://localhost:11434/v1" and s.local is True and s.configured


def test_e2e_no_model_means_not_configured_and_never_a_guess(monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("COPILOT_LLM_PROVIDERS", "ollama")
    monkeypatch.delenv("COPILOT_LLM_OLLAMA_MODEL", raising=False)
    r = ask()
    assert r.mode == "rule_based" and "llm_unavailable" in r.warnings and r.limits["provider_configured"] is False


def test_e2e_a_down_local_server_is_skipped_fast_and_rule_based_still_answers(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    use_ollama(monkeypatch, closed_port_url())
    t0 = time.monotonic()
    r = ask()
    first = time.monotonic() - t0
    t1 = time.monotonic()
    r2 = ask()
    second = time.monotonic() - t1
    base = baseline()
    assert r.mode == "rule_based" and r.answer == base.answer and r.evidence == base.evidence
    assert "llm_unavailable" in r.warnings and "llm_unavailable" in r2.warnings
    assert first < 5.0 and second < 1.0, (first, second)  # never the 30 s local timeout; the second is a cache hit
    assert local.HEALTH.snapshot() and set(local.HEALTH.snapshot().values()) == {"local_down"}


def test_e2e_a_missing_model_is_skipped_without_a_chat_request(ollama, monkeypatch):
    o = ollama(models=["something-else:latest"])
    use_ollama(monkeypatch, o.url)
    r = ask()
    assert r.mode == "rule_based" and "llm_unavailable" in r.warnings
    assert o.tags_requests == 1 and o.chat_requests == []


def test_e2e_down_local_then_cloud_succeeds_and_the_local_one_goes_to_cooldown(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    cloud = FakeProvider()
    try:
        use_ollama(
            monkeypatch,
            closed_port_url(),
            names="ollama,cloud",
            COPILOT_LLM_CLOUD_BASE_URL=cloud.url,
            COPILOT_LLM_CLOUD_MODEL="cloud-model",
            COPILOT_LLM_CLOUD_API_KEY=KEY,
            COPILOT_LLM_CLOUD_TIMEOUT_S="5",
        )
        t0 = time.monotonic()
        r = ask()
        assert r.mode == "llm" and "llm_unavailable" not in r.warnings
        assert time.monotonic() - t0 < 5.0
        assert len(cloud.requests) == 1
        snap = router.ROUTER.snapshot()
        local_key = next(k for k in snap if k.startswith("ollama|"))
        assert snap[local_key]["cooldown_left_s"] > 0  # the router will not even look at it for a while
        assert ask().mode == "llm" and len(cloud.requests) == 2
    finally:
        cloud.close()


def test_e2e_local_first_means_the_cloud_provider_is_never_called(ollama, monkeypatch):
    o = ollama()
    cloud = FakeProvider()
    try:
        use_ollama(
            monkeypatch,
            o.url,
            names="ollama,cloud",
            COPILOT_LLM_CLOUD_BASE_URL=cloud.url,
            COPILOT_LLM_CLOUD_MODEL="cloud-model",
            COPILOT_LLM_CLOUD_API_KEY=KEY,
        )
        assert ask().mode == "llm"
        assert len(o.chat_requests) == 1 and cloud.requests == []
    finally:
        cloud.close()


def test_e2e_local_timeout_applies_to_a_local_provider_on_the_default(ollama, monkeypatch):
    o = ollama()
    use_ollama(monkeypatch, o.url, COPILOT_LLM_LOCAL_TIMEOUT_S="45")
    (s,) = llm.load_chain()
    assert local.prepare(s, None, llm.DEFAULT_TIMEOUT_S).timeout_s == 45.0


def test_logs_carry_no_question_or_answer(ollama, monkeypatch, caplog):
    import logging

    o = ollama()
    use_ollama(monkeypatch, o.url)
    with caplog.at_level(logging.DEBUG):
        ask()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "provider=ollama" in text and "Why is this alert red" not in text and GOOD[:20] not in text


# ----------------------------------------------------------------------------- opt-in live test (deselected unless COPILOT_LLM_LIVE_TEST=1)


@live_llm
def test_live_local_ollama_round_trip():
    """Needs a running Ollama with the model pulled: COPILOT_LLM_PROVIDERS=ollama, COPILOT_LLM_OLLAMA_MODEL=<tag>."""
    (s, *_rest) = [c for c in llm.load_chain() if c.local] or [None]
    if s is None or not s.configured:
        pytest.fail("COPILOT_LLM_LIVE_TEST=1 needs COPILOT_LLM_ENABLED=true, COPILOT_LLM_PROVIDERS=ollama and a model")
    assert local.check(s).ok, "Ollama is not reachable or the model is not pulled (python -m src.copilot.local)"
    r = ask()
    assert r.mode in ("llm", "rule_based")  # a small model may be rejected; nothing may raise and evidence stays intact
    assert r.evidence == baseline().evidence
