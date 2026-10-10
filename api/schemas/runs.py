"""Request shape for POST /api/runs (BC-10 / G-RUN).

Bounds come from the scenario registry (the same constants ``/api/whatif`` enforces), so the run
endpoint, the what-if endpoint and the descriptor schema in ``GET /api/scenarios`` cannot disagree.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.services import scenario_registry as SR


class RunParameters(BaseModel):
    """Optional overrides of a scenario's preset. Names are the descriptor names (``outside_temp``, not ``outside_temp_C``)."""

    model_config = ConfigDict(extra="forbid")

    utilisation: float | None = Field(
        None, ge=SR.UTILISATION_BOUNDS[0], le=SR.UTILISATION_BOUNDS[1], allow_inf_nan=False
    )
    outside_temp: float | None = Field(
        None, ge=SR.OUTSIDE_TEMP_BOUNDS[0], le=SR.OUTSIDE_TEMP_BOUNDS[1], allow_inf_nan=False
    )
    water_stress: float | None = Field(
        None, ge=SR.WATER_STRESS_BOUNDS[0], le=SR.WATER_STRESS_BOUNDS[1], allow_inf_nan=False
    )
    mode: Literal["auto", "free_air", "closed_loop", "evaporative", "hybrid"] | None = None
    chilled_water_temp: float | None = Field(
        None, ge=SR.CHILLED_WATER_TEMP_BOUNDS[0], le=SR.CHILLED_WATER_TEMP_BOUNDS[1], allow_inf_nan=False
    )


class RunCreate(BaseModel):
    """Body of POST /api/runs. ``scenario_id`` is required; ``parameters`` override the preset, key by key."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=64, description="An id from GET /api/scenarios")
    parameters: RunParameters = Field(default_factory=RunParameters)
