"""Pytest plugin for the Copilot LLM tests (Task 24 live opt-in, Task 10 fake model).

``tests/test_copilot_llm.py`` loads it with ``pytest_plugins``. It (1) registers the ``live_llm`` marker so
``--strict-markers`` is satisfied and (2) DESELECTS (not skips) live tests unless ``COPILOT_LLM_LIVE_TEST=1``, so
the CI "no skipped tests" rule is unaffected and ``-m "not live_llm"`` is not needed (it still works).

Why a decorator from here and not ``@pytest.mark.live_llm``: a plugin named by ``pytest_plugins`` is registered after
the test module is imported, and ``--strict-markers`` rejects an unregistered marker at import. The decorator only sets
an attribute; ``pytest_collection_modifyitems`` turns it into the real marker. If the integrator adds the
``live_llm`` line to ``pytest.ini`` the plain marker works too.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable

import pytest

from src.copilot import llm

LIVE_ENV = "COPILOT_LLM_LIVE_TEST"


def live_llm(func):
    func._live_llm = True
    return func


def pytest_configure(config):
    config.addinivalue_line("markers", "live_llm: talks to a real LLM provider; opt in with COPILOT_LLM_LIVE_TEST=1")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    live = [i for i in items if getattr(getattr(i, "obj", None), "_live_llm", False)]
    for item in live:
        item.add_marker(pytest.mark.live_llm)
    if live and os.environ.get(LIVE_ENV) != "1":
        config.hook.pytest_deselected(items=live)
        items[:] = [i for i in items if i not in live]


# ----------------------------------------------------------------------------- Task 10: a TEST-ONLY fake model
#
# NOT a product component and never imported by application code. It replaces ``src.copilot.llm._call_provider`` (the one
# function that talks to a provider) so the REAL validator, the REAL answer builder and (in the HTTP tests) the REAL route
# run against replies the test chooses: an invented number, a jailbreak, a timeout. It cannot make the product accept
# anything: whatever it returns still goes through ``llm.validate``.

FAKE_BASE_URL = "http://fake-provider.invalid/v1"
FAKE_MODEL = "fake-model-test-only"
FAKE_KEY = "sk-fake-test-only-key-0451"


def reply(text: str, used: tuple[str, ...] = ("E1",)) -> str:
    """The JSON body the system policy asks the model for."""
    return json.dumps({"answer": text, "used_evidence": list(used)})


def data_block(messages: list[dict[str, str]]) -> dict[str, Any]:
    """The JSON between BEGIN_DATA and END_DATA in the user message (question, evidence, draft, allowed links)."""
    lines = messages[-1]["content"].splitlines()
    assert lines[0].startswith("BEGIN_DATA ") and lines[-1].startswith("END_DATA "), "no data block"
    return json.loads("\n".join(lines[1:-1]))


def evidence_id(messages: list[dict[str, str]], field: str) -> str | None:
    """The id of the evidence item for ``field`` in the request, so a reply never hard-codes ``E1``."""
    return next((e["id"] for e in data_block(messages)["evidence"] if e["field"] == field), None)


class FakeLlm:
    """Scripted stand-in for the provider call. ``calls`` keeps every ``messages`` list the product sent."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.settings = llm.LlmSettings(
            enabled=True, base_url=FAKE_BASE_URL, model=FAKE_MODEL, api_key=FAKE_KEY, timeout_s=2.0
        )
        self.release = threading.Event()  # lets a hanging reply end at test teardown
        self._behaviour: Callable[[list[dict[str, str]]], str] = self._unscripted

    @staticmethod
    def _unscripted(messages: list[dict[str, str]]) -> str:
        raise llm.ProviderError("network")

    def __call__(self, settings: llm.LlmSettings, messages: list[dict[str, str]]) -> tuple[str, str | None]:
        self.calls.append(messages)
        return self._behaviour(messages), "fake-req-1"

    # -- scripting ------------------------------------------------------------------------------------------------
    def say(self, content: str | Callable[[list[dict[str, str]]], str]) -> None:
        """Return ``content`` (a string, or a function of the request) as the provider's reply."""
        self._behaviour = content if callable(content) else (lambda _m: content)

    def fail(self, code: str) -> None:
        """Raise the adapter's own provider error (``timeout``, ``network``, ``http_5xx``, ...)."""

        def _raise(_m: list[dict[str, str]]) -> str:
            raise llm.ProviderError(code)

        self._behaviour = _raise

    def crash(self) -> None:
        """Raise something the adapter does not expect, to prove nothing escapes to the client."""

        def _raise(_m: list[dict[str, str]]) -> str:
            raise RuntimeError("fake provider crashed")

        self._behaviour = _raise

    def hang(self) -> None:
        """Block until the test ends (a provider that never answers)."""

        def _wait(_m: list[dict[str, str]]) -> str:
            self.release.wait(10)
            raise llm.ProviderError("timeout")

        self._behaviour = _wait


@pytest.fixture
def fake_llm(monkeypatch):
    """A configured provider whose replies the test scripts. Both the explicit ``fake.settings`` and the environment
    (the route reads the environment) point at it; no socket is ever opened."""
    fake = FakeLlm()
    monkeypatch.setattr(llm, "_call_provider", fake)
    monkeypatch.delenv("COPILOT_LLM_API_KEY_FILE", raising=False)
    for key, value in {
        "COPILOT_LLM_ENABLED": "true",
        "COPILOT_LLM_BASE_URL": FAKE_BASE_URL,
        "COPILOT_LLM_MODEL": FAKE_MODEL,
        "COPILOT_LLM_API_KEY": FAKE_KEY,
        "COPILOT_LLM_TIMEOUT_S": "2",
    }.items():
        monkeypatch.setenv(key, value)
    yield fake
    fake.release.set()
