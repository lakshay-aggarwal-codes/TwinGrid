"""Function run by the ``rq worker`` for POST /api/runs (BC-10 / G-RUN).

Same worker, queue and JSON serializer as ``src/task_jobs.py``; kept in its own module so the training
job file is untouched. The worker imports this module by name, so it must stay importable without a
request context.

A run is one isolated 24 h what-if on the simulated plant, exactly the computation behind
``GET /api/whatif`` (``twin_service.compute_whatif``). It adds no physics.

Failure contract: the job raises ``RunFailed(<code>)``; the API reads the code back from the failed RQ
job and returns only that code, never the exception text, a traceback or a path.
"""

from __future__ import annotations

from typing import Any

FAILURE_INVALID_INPUT = "invalid_input"
FAILURE_INTERNAL = "internal_error"


class RunFailed(Exception):
    """The run could not produce a result. ``code`` is one of the public failure codes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def run_whatif_job(run_id: str, scenario_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Compute one what-if run. ``parameters`` is fully resolved (all five descriptor names present)."""
    from api.serialization import to_jsonable
    from api.services import twin_service
    from src.digital_twin import InvalidInputError
    from src.versions import active_physics_version

    try:
        physics_version = active_physics_version()
        raw = twin_service.compute_whatif(
            parameters["utilisation"],
            parameters["outside_temp"],
            parameters["water_stress"],
            parameters["mode"],
            parameters["chilled_water_temp"],
        )
    except InvalidInputError as exc:
        raise RunFailed(FAILURE_INVALID_INPUT) from exc
    except Exception as exc:  # noqa: BLE001 - any other failure is reported as a generic code, never its text
        raise RunFailed(FAILURE_INTERNAL) from exc

    outputs = to_jsonable(raw)
    outputs.pop("inputs", None)  # the resolved inputs are returned once, under descriptor names, as ``parameters``
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "physics_version": physics_version,
        "outputs": outputs,
    }
