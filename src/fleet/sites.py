"""Five SIMULATED sites. Each is a set of the what-if scenario parameters (utilisation, outside temperature, water
stress) run through the same digital twin as the main facility. They are not real facilities and have no real names.
"""

from __future__ import annotations

from dataclasses import dataclass

LABEL = "Simulated sites: the digital twin run under five different parameter sets. Not real facilities."


@dataclass(frozen=True)
class SiteSpec:
    id: str
    name: str
    climate: str
    utilisation: float  # fraction of capacity, 0..1 (scenario parameter "utilisation")
    outside_temp_c: float  # scenario parameter "outside_temp"
    water_stress: float  # scenario parameter "water_stress", 0..1


SITES: tuple[SiteSpec, ...] = (
    SiteSpec("sim-a", "Simulated site A", "Temperate, moderate load", 0.60, 16.0, 0.1),
    SiteSpec("sim-b", "Simulated site B", "Hot and dry, water-stressed", 0.70, 38.0, 0.8),
    SiteSpec("sim-c", "Simulated site C", "Cold, light load", 0.45, 2.0, 0.0),
    SiteSpec("sim-d", "Simulated site D", "Hot and humid, high load", 0.80, 31.0, 0.3),
    SiteSpec("sim-e", "Simulated site E", "Temperate, peak load", 0.95, 20.0, 0.1),
)

BY_ID = {s.id: s for s in SITES}
