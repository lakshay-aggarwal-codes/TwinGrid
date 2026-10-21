"""Pytest plugin for the opt-in live LLM test (Task 24).

``tests/test_copilot_llm.py`` loads it with ``pytest_plugins``. It (1) registers the ``live_llm`` marker so
``--strict-markers`` is satisfied and (2) DESELECTS (not skips) live tests unless ``COPILOT_LLM_LIVE_TEST=1``, so
the CI "no skipped tests" rule is unaffected and ``-m "not live_llm"`` is not needed (it still works).

Why a decorator from here and not ``@pytest.mark.live_llm``: a plugin named by ``pytest_plugins`` is registered after
the test module is imported, and ``--strict-markers`` rejects an unregistered marker at import. The decorator only sets
an attribute; ``pytest_collection_modifyitems`` turns it into the real marker. If the integrator adds the
``live_llm`` line to ``pytest.ini`` the plain marker works too.
"""

from __future__ import annotations

import os

import pytest

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
