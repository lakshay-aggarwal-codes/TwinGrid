"""
Fast DigitalTwin - optimized for real-time dashboard performance.

This module provides the same API as the original DigitalTwin but with
massive performance optimizations for sub-2 second 24-hour simulations.
"""

# Import the optimized implementation
from .digital_twin_optimized import (
    DigitalTwinOptimized,
    DataCentreState,
    CoolingMode,
    SPECIFIC_HEAT_AIR_J_KG_K,
    AIR_DENSITY_KG_M3,
    INTERVAL_MINUTES,
    INLET_TEMP_MIN,
    INLET_TEMP_MAX,
    OUTLET_TEMP_MAX,
    PUE_MAX_SAFE,
)

# Provide the same class name for drop-in replacement
DigitalTwin = DigitalTwinOptimized

__all__ = [
    "DigitalTwin",
    "DigitalTwinOptimized",
    "DataCentreState", 
    "CoolingMode",
    "SPECIFIC_HEAT_AIR_J_KG_K",
    "AIR_DENSITY_KG_M3",
    "INTERVAL_MINUTES",
    "INLET_TEMP_MIN",
    "INLET_TEMP_MAX",
    "OUTLET_TEMP_MAX",
    "PUE_MAX_SAFE",
]
