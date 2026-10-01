"""pytest plugin for T0 acceptance criterion 3: a TEMPORARY, in-memory 1% change to a water
constant. No file is edited, so there is nothing to revert or accidentally commit.

    $env:TWINGRID_MUTATE = "src.digital_twin:WATER_FLOW_SCALE_LPM_PER_KW:1.01"   # PowerShell
    python -m pytest -p tests.characterization.tools.mutation_plugin tests/characterization -o addopts=""

Expected: at least one golden test fails.
"""

from __future__ import annotations

import importlib
import os


def pytest_configure(config):  # noqa: D401
    spec = os.environ.get("TWINGRID_MUTATE")
    if not spec:
        return
    module_name, attr, factor = spec.split(":")
    module = importlib.import_module(module_name)
    setattr(module, attr, getattr(module, attr) * float(factor))
    print(f"[mutation] {module_name}.{attr} *= {factor} -> {getattr(module, attr)!r}")
