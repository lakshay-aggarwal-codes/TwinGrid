"""T0 characterization suite: markers and fixtures. Test-only; no production edits.

Marker contract (roadmap T0 constraint 6):
  * ``legacy_behavior("<TaskID>")`` -- passes today; the owning task deletes or rewrites it.
  * ``xfail(strict=True, raises=AssertionError, reason="<TaskID>")`` -- target behaviour that
    does not exist yet; ``strict`` makes an unexpected pass a failure, ``raises=AssertionError``
    makes a fixture/setup error a failure instead of a silent xfail.
"""

from __future__ import annotations

import os

# Must be set BEFORE api.* is imported (api/auth.py refuses to import without it) -- same
# convention as tests/api/conftest.py.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")
os.environ["ENVIRONMENT"] = "development"

import pytest  # noqa: E402

# Re-use the existing HTTP-test fixtures verbatim instead of copying them.
from tests.api.conftest import (  # noqa: E402,F401
    client,
    count_rows,
    engine,
    make_user,
    operator_headers,
    session_maker,
    viewer_headers,
)
from tests.characterization import golden_support  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "legacy_behavior(task_id): characterizes behaviour that task <task_id> will change; "
        "that task deletes or rewrites the test",
    )


@pytest.fixture
def frozen_env():
    with golden_support.frozen_environment():
        yield


@pytest.fixture
def isolated_shared_twin(frozen_env):
    """Frozen clock + fresh shared-twin singleton (restored afterwards)."""
    with golden_support.fresh_shared_twin():
        yield


@pytest.fixture
def tick_env():
    with golden_support.live_tick_environment() as session:
        yield session
