"""Physics v1 regression freeze (see the "meta" block: it detects change, it does not validate the physics).

If this fails after an intentional physics change: bump PHYSICS_VERSION in src/versions.py (a physics change
is a new version), regenerate with ``python -m tests.golden.generate_legacy_goldens --version <new>``, and
review the diff -- never silently regenerate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from tests.golden import scenarios
from tests.golden.test_legacy_0_goldens import assert_close

GOLDEN = json.loads(Path(__file__).with_name("v1_goldens.json").read_text())


def test_metadata():
    assert GOLDEN["meta"]["physics_version"] == "1"
    assert "REGRESSION FREEZE" in GOLDEN["meta"]["note"]


def test_grid_states():
    with scenarios.physics_env("1"):
        assert_close(scenarios.grid_states(), GOLDEN["grid_states"], "grid_states")


def test_live_sequence():
    with scenarios.physics_env("1"):
        assert_close(scenarios.live_sequence(), GOLDEN["live_sequence"], "live_sequence")


def test_compute_whatif():
    with mock.patch.dict(os.environ, {"PHYSICS_VERSION": "1"}):
        assert_close(scenarios.whatif_cases(), GOLDEN["whatif"], "whatif")


def test_optimizer_environment_rollout():
    with scenarios.physics_env("1"):
        assert_close(scenarios.env_rollout(), GOLDEN["env_rollout"], "env_rollout")
