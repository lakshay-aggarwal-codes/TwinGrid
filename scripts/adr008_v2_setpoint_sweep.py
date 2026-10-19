#!/usr/bin/env python3
"""Evidence for docs/adr/008: steady-state inlet/outlet of physics v2 versus the chilled-water setpoint.

    python scripts\\adr008_v2_setpoint_sweep.py

Pure physics (src/physics/v2.py, default parameters, closed_loop, constant inputs, 2 simulated days at 300 s). It prints the
settled server inlet / outlet temperature for a grid of IT load, outside temperature and setpoint, plus how many 5-minute
steps the actuator needs to travel from the 10 C reset setpoint to a 25 C request. Nothing is written. Simulator output only:
it says nothing about a real facility. Report the machine and Python version when you quote the numbers.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.physics import v2  # noqa: E402
from src.physics.params import DEFAULT_PHYSICS_PARAMS as PARAMS  # noqa: E402

DT_S = 300.0
STEPS = 288 * 2
SETPOINTS_C = (10, 16, 20, 25, 30)


def settle(util: float, outside_c: float, chw_c: float) -> v2.DynamicState:
    inputs = v2.StepInputs(util, outside_c, 50.0, "closed_loop", float(chw_c))
    state = v2.initial_state(inputs, PARAMS, 10.0)
    for _ in range(STEPS):
        state = v2.step(state, inputs, DT_S, PARAMS).state
    return state


def steps_to_reach(request_c: float, target_c: float) -> int:
    inputs = v2.StepInputs(0.5, 25.0, 50.0, "closed_loop", request_c)
    state = v2.initial_state(inputs, PARAMS, 10.0)
    for n in range(1, 1001):
        state = v2.step(state, inputs, DT_S, PARAMS).state
        if state.t_chw_applied_c >= target_c:
            return n
    return -1


def main() -> int:
    print(f"python {platform.python_version()} on {platform.platform()}")
    print("closed_loop, constant inputs, 2 simulated days; cells are chw_setpoint: T_in/T_out (C)")
    for util in (0.3, 0.7, 1.0):
        for outside in (20, 35):
            cells = "  ".join(
                f"{c}: {s.t_in_c:.1f}/{s.t_out_c:.1f}" for c in SETPOINTS_C for s in [settle(util, outside, c)]
            )
            print(f"util {util:.1f} outside {outside:>2} C | {cells}")
    print(
        f"5-minute steps to reach 24.5 C from the 10 C reset setpoint with a 25 C request: {steps_to_reach(25.0, 24.5)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
