"""T0 constraint 1: establish (and pin) where nondeterminism can come from.

Findings encoded here:
  * src/digital_twin.py and src/carbon_provider.py contain no ``random`` / ``np.random`` use.
  * The only wall-clock read in the twin is ``datetime.now()`` as the default ``start_time``.
  * ``_tick()`` is nondeterministic through ``datetime.now()`` and ``random.uniform``.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.digital_twin import CoolingMode, DigitalTwin
from tests.characterization import golden_support as gs

REPO = gs.REPO_ROOT


def _names_used(path: Path) -> tuple[set[str], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    attr_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
                attr_calls.append(f"{base.value.id}.{base.attr}.{node.attr}")
            elif isinstance(base, ast.Name):
                attr_calls.append(f"{base.id}.{node.attr}")
    return imported, attr_calls


@pytest.mark.parametrize("relative", ["src/digital_twin.py", "src/carbon_provider.py"])
def test_twin_sources_use_no_randomness(relative):
    imported, attrs = _names_used(REPO / relative)
    assert "random" not in imported
    assert not [a for a in attrs if a.startswith(("np.random.", "numpy.random.", "random."))]


def test_twin_wall_clock_read_is_only_the_default_start_time():
    """T12: the only wall-clock read is the default start time, and it goes through the one clock."""
    text = (REPO / "src/digital_twin.py").read_text(encoding="utf-8")
    assert "datetime.now(" not in text and "utcnow(" not in text
    assert text.count("utc_now()") == 1
    assert "self._time = start_time if start_time is not None else utc_now()" in text


def test_twin_is_deterministic_given_explicit_start_time():
    def run():
        twin = DigitalTwin(start_time=gs.FIXED_NOW)
        rows = []
        for u, t in [(0.3, 12.0), (0.8, 30.0), (0.5, 20.0), (0.9, 38.0)]:
            s = twin.step({"utilisation": u, "outside_temp_C": t, "cooling_mode": CoolingMode.HYBRID})
            rows.append(s.to_dict())
        return rows

    with gs.frozen_environment():
        assert run() == run()


def test_compute_state_is_deterministic_under_frozen_clock():
    from api.services.twin_service import compute_state

    with gs.frozen_environment():
        a = compute_state(0.6, 22.0, 0.3, "auto", live=False)
        b = compute_state(0.6, 22.0, 0.3, "auto", live=False)
    assert a == b


def test_compute_whatif_is_deterministic_under_frozen_clock():
    from api.services.twin_service import compute_whatif

    with gs.frozen_environment():
        a = compute_whatif(0.7, 30.0, 0.2, "hybrid", 7.0)
        b = compute_whatif(0.7, 30.0, 0.2, "hybrid", 7.0)
    assert a == b


def test_unfrozen_twin_timestamp_follows_the_wall_clock():
    """Why freezing is needed: without it the state timestamp is 'now' (+5 min)."""
    before = datetime.now(timezone.utc)
    ts = DigitalTwin().step({"utilisation": 0.5, "outside_temp_C": 20.0}).timestamp
    after = datetime.now(timezone.utc)
    assert ts.tzinfo is not None and ts.utcoffset() == timedelta(0)  # T12: default clock is aware UTC
    assert before + timedelta(minutes=5) <= ts <= after + timedelta(minutes=5)


def test_carbon_fallback_is_active_in_this_snapshot():
    """Goldens assume the flat 475 g/kWh fallback (no data/cleaned/carbon_intensity.csv)."""
    with gs.frozen_environment():
        twin = DigitalTwin()
    assert twin.carbon_data_is_real is False
    assert set(float(x) for x in twin._carbon_intensity_by_hour) == {475.0}


def test_tick_is_reproducible_with_same_seed_and_differs_with_another():
    import api.services.live_broadcast_service as lbs

    def run(seed):
        async def go():
            with gs.live_tick_environment(seed):
                return [await lbs._tick() for _ in range(3)]

        return asyncio.run(go())

    def stable(payloads):
        # ts_ingest and anomaly_status.scored_at are the real wall clock by design (T1a/T3);
        # everything else must be reproducible.
        return [
            {
                k: ({a: b for a, b in v.items() if a != "scored_at"} if k == "anomaly_status" else v)
                for k, v in p.items()
                if k != "ts_ingest"
            }
            for p in payloads
        ]

    assert stable(run(7)) == stable(run(7))
    a, b = run(7), run(8)
    assert [p["outside_temp_C"] for p in a] != [p["outside_temp_C"] for p in b]
