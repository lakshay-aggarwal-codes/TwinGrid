"""Fixtures for the CP-0 Copilot characterization tests.

The LLM path is driven the way production drives it: through the ``COPILOT_LLM_*`` environment variables and
``answer.answer_question``. A real HTTP server on 127.0.0.1 plays the provider (so timeouts, redirects and status codes
are exercised through ``requests``, not stubbed). No external network is touched. Because the tests only use the
environment contract, they keep passing when later tasks refactor ``llm.py`` behind the provider layer (CP-1 rule).
"""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

MODEL = "char-model-1"
KEY = "sk-char-test-key-0451"
GOOD = "Alert 42 scored {{E1}} against a threshold of {{E2}}. The cause is not determined by available evidence."
ALL_ENV = (
    "COPILOT_LLM_ENABLED",
    "COPILOT_LLM_BASE_URL",
    "COPILOT_LLM_MODEL",
    "COPILOT_LLM_API_KEY",
    "COPILOT_LLM_API_KEY_FILE",
    "COPILOT_LLM_TIMEOUT_S",
    "COPILOT_LLM_MAX_OUTPUT_TOKENS",
)


def envelope(content: Any, rid: str | None = "chatcmpl-char-1") -> str:
    return json.dumps({"id": rid, "choices": [{"message": {"role": "assistant", "content": content}}]})


def model_reply(text: str, used: tuple[str, ...] = ("E1", "E2")) -> str:
    """The JSON the system policy asks the model for."""
    return json.dumps({"answer": text, "used_evidence": list(used)})


class FakeProvider:
    """A scripted OpenAI-compatible server. Set ``status``/``body``/``delay``/``headers`` before the call."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.body: str | bytes | None = None  # None -> a normal envelope around ``content``
        self.content: str = model_reply(GOOD)
        self.delay = 0.0
        self.headers: dict[str, str] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": json.loads(raw),
                    }
                )
                if outer.delay:
                    time.sleep(outer.delay)
                payload = outer.body if outer.body is not None else envelope(outer.content)
                data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in outer.headers.items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def say(self, text: str, used: tuple[str, ...] = ("E1", "E2")) -> None:
        self.content = model_reply(text, used)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _clean_copilot_env(monkeypatch):
    """No COPILOT_LLM_* value from the developer's shell or .env may reach these tests; loopback bypasses any proxy."""
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def provider():
    p = FakeProvider()
    yield p
    p.close()


@pytest.fixture
def trap():
    """A second server that must never be contacted (redirect target)."""
    p = FakeProvider()
    yield p
    p.close()


@pytest.fixture
def configure(monkeypatch, provider):
    """Point the environment at the fake provider (the production configuration contract)."""

    def _configure(**overrides: str | None) -> None:
        values: dict[str, str | None] = {
            "COPILOT_LLM_ENABLED": "true",
            "COPILOT_LLM_BASE_URL": provider.url,
            "COPILOT_LLM_MODEL": MODEL,
            "COPILOT_LLM_API_KEY": KEY,
            "COPILOT_LLM_TIMEOUT_S": "5",
        }
        values.update(overrides)
        for name, value in values.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)

    return _configure


@pytest.fixture
def free_port_url() -> str:
    """A loopback URL nobody listens on (connection refused)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


@pytest.fixture
def outcomes(caplog):
    """The ``outcome=`` words the LLM adapter logged, in order."""
    caplog.set_level(logging.INFO, logger="src.copilot.llm")

    def _outcomes() -> list[str]:
        found = []
        for rec in caplog.records:
            m = re.search(r"outcome=([A-Za-z0-9_]+)", rec.getMessage())
            if m:
                found.append(m.group(1))
        return found

    return _outcomes
