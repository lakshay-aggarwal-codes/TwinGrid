"""Shared helpers for the T0 characterization / golden suite.

Nothing in here changes production code. Determinism is obtained from the
tests by (a) freezing ``datetime.now()`` where production modules call it,
(b) pointing the carbon provider at a non-existent file so the documented flat
fallback is always used, (c) seeding ``random`` around ``_tick`` and (d)
resetting module-level singletons through ``unittest.mock.patch.object``.

Regenerate the goldens (only on unmodified, reviewed code):

    python -m tests.characterization.golden_support --regenerate
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import json
import os
import platform
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"

REL_TOL = 1e-9  # roadmap T0 constraint 5: relative 1e-9 unless a value is documented as noisy
ABS_TOL = 1e-12  # guards comparisons against exact zeros only

FIXED_NOW = datetime(2026, 1, 1, 12, 30, 0)
# T12: the production clock is src.timeutil.utc_now() (aware UTC). The same wall reading, frozen as an
# aware UTC instant, with SITE_TIMEZONE=UTC during goldens, keeps every hour-of-day (and therefore every
# numeric) identical to the pre-T12 goldens; only timestamp *fields* gain an explicit "+00:00".
FIXED_NOW_UTC = datetime(2026, 1, 1, 12, 30, 0, tzinfo=timezone.utc)
GOLDEN_SITE_TIMEZONE = "UTC"
TICK_SEED = 20260101
PHYSICS_VERSION_LABEL = "legacy-0 (implicit)"
COMMIT_LABEL = "unknown \u2014 no .git in snapshot"

HASHED_SOURCES = (
    "src/digital_twin.py",
    "api/services/twin_service.py",
    "api/services/live_broadcast_service.py",
)

# --------------------------------------------------------------------------- scenario grids
STATE_UTILISATIONS = (0.1, 0.5, 0.9)
STATE_OUTSIDE_TEMPS = (-5.0, 10.0, 25.0, 40.0)
STATE_WATER_STRESSES = (0.0, 0.5, 1.0)
STATE_MODES = ("auto", "free_air", "closed_loop", "evaporative", "hybrid")

WHATIF_UTILISATIONS = (0.3, 0.9)
WHATIF_OUTSIDE_TEMPS = (10.0, 35.0)
WHATIF_WATER_STRESSES = (0.0, 0.8)
WHATIF_MODES = ("auto", "closed_loop", "evaporative")
WHATIF_CHILLED_WATER_TEMPS = (7.0,)
WHATIF_EXTRA_CHILLED_CASES = ((0.65, 22.0, 0.0, "closed_loop", 5.0), (0.65, 22.0, 0.0, "closed_loop", 12.0))

SIMULATE_CASES = ((24, 0.7, 25.0, 0.3),)

PUE_VALUES = (1.0, 1.1, 1.2, 1.2000001, 1.3, 1.4, 1.4000001, 1.5, 1.56, 1.6, 1.6000001, 1.61, 2.0, 3.5)

# A fixed 20-step live-twin sequence: (utilisation, outside_temp, water_stress, mode)
LIVE_SEQUENCE: tuple[tuple[float, float, float, str], ...] = tuple(
    (
        round(0.3 + 0.03 * i, 6),
        round(8.0 + 1.7 * i, 6),
        round(0.05 * (i % 8), 6),
        ("auto", "auto", "evaporative", "hybrid", "closed_loop", "free_air", "auto", "evaporative", "auto", "auto")[
            i % 10
        ],
    )
    for i in range(20)
)

TICKS = 5


# --------------------------------------------------------------------------- environment control
def _frozen_datetime_class() -> type:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401 - mimic datetime.now
            return FIXED_NOW_UTC if tz is None else FIXED_NOW_UTC.astimezone(tz)

    return _FrozenDateTime


@contextlib.contextmanager
def frozen_environment() -> Iterator[None]:
    """Freeze the single production clock (``src.timeutil``) at ``FIXED_NOW_UTC``, pin
    ``SITE_TIMEZONE`` to UTC, and force the carbon provider's flat-fallback branch.
    Restores everything on exit."""
    import src.carbon_provider as carbon_provider
    import src.timeutil as timeutil

    frozen = _frozen_datetime_class()
    patches = [
        mock.patch.object(timeutil, "datetime", frozen),
        mock.patch.dict(os.environ, {"SITE_TIMEZONE": GOLDEN_SITE_TIMEZONE}),
        mock.patch.object(carbon_provider, "CLEANED_CARBON_PATH", REPO_ROOT / "data" / "cleaned" / "__t0_absent__.csv"),
    ]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


@contextlib.contextmanager
def fresh_shared_twin() -> Iterator[None]:
    """Replace the module-level shared twin singleton with ``None`` for the duration."""
    import api.services.twin_service as twin_service

    with mock.patch.object(twin_service, "_twin", None):
        yield


class FakeSession:
    """Stand-in for ``database.get_session()``'s async context manager."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:  # T3: _tick flushes to obtain the reading id
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


@contextlib.contextmanager
def live_tick_environment(seed: int = TICK_SEED) -> Iterator[FakeSession]:
    """Everything ``_tick()`` needs to be reproducible: frozen clock, seeded
    ``random``, fresh shared twin, fresh water-stress walk, stubbed session."""
    import api.services.anomaly_service as anomaly_service
    import api.services.live_broadcast_service as lbs
    import api.services.telemetry_window as telemetry_window

    session = FakeSession()
    saved_state = random.getstate()
    random.seed(seed)
    try:
        with (
            frozen_environment(),
            fresh_shared_twin(),
            # T3: fresh window + pipeline so a run never inherits samples/episodes from another test
            mock.patch.object(telemetry_window, "_provider", telemetry_window.InMemoryTelemetryWindow()),
            mock.patch.object(anomaly_service, "_pipeline", anomaly_service.AnomalyPipeline()),
            mock.patch.object(lbs, "_water_stress_state", 0.2),
            mock.patch.object(lbs, "_tick_seq", 0),  # T1a: first tick in a run is seq=1
            mock.patch.object(lbs, "get_session", lambda: session),
        ):
            yield session
    finally:
        random.setstate(saved_state)


# --------------------------------------------------------------------------- scenario runners
def _plain(value: Any) -> Any:
    """Plain-JSON form used inside goldens (no dependency on api.serialization)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (int, float, str, bool)):
        return value.value
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def case_id(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def run_state_grid() -> dict[str, Any]:
    from api.services.twin_service import compute_state

    out: dict[str, Any] = {}
    with frozen_environment():
        for u, t, w, m in itertools.product(STATE_UTILISATIONS, STATE_OUTSIDE_TEMPS, STATE_WATER_STRESSES, STATE_MODES):
            out[case_id(f"u={u}", f"t={t}", f"w={w}", f"mode={m}")] = _plain(compute_state(u, t, w, m, live=False))
    return out


def whatif_cases() -> list[tuple[float, float, float, str, float]]:
    cases = [
        (u, t, w, m, c)
        for u, t, w, m, c in itertools.product(
            WHATIF_UTILISATIONS,
            WHATIF_OUTSIDE_TEMPS,
            WHATIF_WATER_STRESSES,
            WHATIF_MODES,
            WHATIF_CHILLED_WATER_TEMPS,
        )
    ]
    cases.extend(WHATIF_EXTRA_CHILLED_CASES)
    return cases


def run_whatif_grid() -> dict[str, Any]:
    from api.services.twin_service import compute_whatif

    out: dict[str, Any] = {}
    with frozen_environment():
        for u, t, w, m, c in whatif_cases():
            out[case_id(f"u={u}", f"t={t}", f"w={w}", f"mode={m}", f"chw={c}")] = _plain(compute_whatif(u, t, w, m, c))
    return out


def run_simulate_cases() -> dict[str, Any]:
    from api.services.twin_service import compute_simulation

    out: dict[str, Any] = {}
    with frozen_environment():
        for hours, u, t, s in SIMULATE_CASES:
            out[case_id(f"hours={hours}", f"u={u}", f"t={t}", f"stress={s}")] = _plain(
                compute_simulation(hours, u, t, s)
            )
    return out


def run_live_sequence() -> dict[str, Any]:
    """20 steps through the SHARED live twin; captures per-step output and the
    twin's internal accumulators after every step."""
    import api.services.twin_service as twin_service

    steps = []
    with frozen_environment(), fresh_shared_twin():
        for u, t, w, m in LIVE_SEQUENCE:
            result = _plain(twin_service.compute_state(u, t, w, m, live=True))
            twin = twin_service.get_twin()
            steps.append(
                {
                    "inputs": {"utilisation": u, "outside_temp": t, "water_stress": w, "mode": m},
                    "output": result,
                    "accumulators": {
                        "water_consumed_cumulative_L": twin._water_consumed_cumulative_L,
                        "applied_chilled_water_temp_C": twin._applied_chilled_water_temp_C,
                        "inlet_temp_C": twin._inlet_temp_C,
                        "outlet_temp_C": twin._outlet_temp_C,
                        "time": twin._time.isoformat(),
                    },
                }
            )
    return {"steps": steps}


def run_benchmark_pue() -> dict[str, Any]:
    from src.facility_benchmarking import benchmark_pue

    return {str(v): _plain(benchmark_pue(v)) for v in PUE_VALUES}


def _type_name(value: Any) -> str:
    return type(value).__name__


def run_ws_ticks() -> dict[str, Any]:
    """Run ``_tick()`` ``TICKS`` times under the controlled environment."""
    import asyncio

    import api.services.live_broadcast_service as lbs

    async def _go() -> dict[str, Any]:
        payloads = []
        with live_tick_environment() as session:
            for _ in range(TICKS):
                payloads.append(await lbs._tick())
            persisted = [{"class": type(o).__name__, "source": getattr(o, "source", None)} for o in session.added]
            commits = session.commits
        return {
            "key_set": sorted(payloads[0].keys()),
            "value_types": {k: _type_name(v) for k, v in sorted(payloads[0].items())},
            "payloads": payloads,
            "persistence_per_run": {"rows_added": persisted, "commits": commits},
        }

    return asyncio.run(_go())


# --------------------------------------------------------------------------- golden I/O
def source_sha256(relative: str) -> str:
    return hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()


def metadata(scenario_id: str) -> dict[str, Any]:
    import numpy

    return {
        "scenario_id": scenario_id,
        "commit": COMMIT_LABEL,
        "physics_version": PHYSICS_VERSION_LABEL,
        "source_sha256": {p: source_sha256(p) for p in HASHED_SOURCES},
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "generated_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "frozen_now": FIXED_NOW_UTC.isoformat(),
        "tolerance": {"relative": REL_TOL, "absolute": ABS_TOL},
        "note": (
            "Informational metadata only: comparisons use the 'data' block. Hash mismatches are expected "
            "once later tasks legitimately edit the hashed files."
        ),
    }


def golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def write_golden(name: str, data: Any) -> Path:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = golden_path(name)
    payload = {"metadata": metadata(name), "data": data}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_golden(name: str) -> dict[str, Any]:
    return json.loads(golden_path(name).read_text(encoding="utf-8"))


def assert_matches(actual: Any, expected: Any, path: str = "$") -> None:
    """Deep comparison: floats within REL_TOL, everything else exact."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        assert actual is expected or actual == expected, f"{path}: {actual!r} != {expected!r}"
        assert type(actual) is type(expected), f"{path}: type {type(actual).__name__} != {type(expected).__name__}"
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual).__name__}"
        assert set(actual) == set(expected), (
            f"{path}: key mismatch; missing={sorted(set(expected) - set(actual))} "
            f"extra={sorted(set(actual) - set(expected))}"
        )
        for k in expected:
            assert_matches(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual).__name__}"
        assert len(actual) == len(expected), f"{path}: length {len(actual)} != {len(expected)}"
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_matches(a, e, f"{path}[{i}]")
    elif isinstance(expected, float) or isinstance(actual, float):
        assert isinstance(actual, (int, float)) and isinstance(
            expected, (int, float)
        ), f"{path}: non-numeric {actual!r} vs {expected!r}"
        diff = abs(actual - expected)
        bound = max(ABS_TOL, REL_TOL * abs(expected))
        assert diff <= bound, f"{path}: {actual!r} != {expected!r} (|diff|={diff:.3e} > {bound:.3e})"
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def assert_frozen_subset(actual: dict[str, Any], expected: dict[str, Any], path: str = "$") -> None:
    """Every key frozen in ``expected`` must be present in ``actual`` with an equal value.
    ``actual`` may gain keys (additive change). Used where a later task is allowed to add fields."""
    missing = set(expected) - set(actual)
    assert not missing, f"{path}: frozen keys missing: {sorted(missing)}"
    for k, v in expected.items():
        assert_matches(actual[k], v, f"{path}.{k}")


GOLDEN_BUILDERS = {
    "compute_state_grid": run_state_grid,
    "compute_whatif_grid": run_whatif_grid,
    "compute_simulation_cases": run_simulate_cases,
    "live_twin_sequence": run_live_sequence,
    "benchmark_pue": run_benchmark_pue,
    "ws_tick_sequence": run_ws_ticks,
}


def regenerate_all() -> list[Path]:
    paths = []
    for name, builder in GOLDEN_BUILDERS.items():
        paths.append(write_golden(name, builder()))
    return paths


if __name__ == "__main__":  # pragma: no cover
    if "--regenerate" not in sys.argv:
        print(__doc__)
        raise SystemExit(2)
    sys.path.insert(0, str(REPO_ROOT))
    import os

    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")
    os.environ.setdefault("ENVIRONMENT", "development")
    for p in regenerate_all():
        print("wrote", p.relative_to(REPO_ROOT))
