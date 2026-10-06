"""PhysicsParams -- the frozen, hashable parameter surface of physics v2 (roadmap 13.2).

Every number that shapes a v2 trajectory is a field here; nothing is read from the environment or from module
globals inside the equations. ``PhysicsParams`` is frozen (so it is hashable and cannot drift mid-run) and
``params_hash()`` is a SHA-256 over a canonical JSON encoding of all fields. The hash is part of the physics
identity (``src/versions.py::physics_identity``) so two runs with different parameters are never mixed.

STATUS: UNCALIBRATED. The defaults are PROPOSED engineering values. Those inherited from physics v1 (COP
curve, latent-heat water bound, capacity margin/derate, supply floor, ...) are the v1 numbers verbatim -- that
is what makes the v2 steady state equal v1's -- and tests/test_physics_v2.py asserts they still match the v1
module constants. The values introduced by v2 (``thermal_capacitance_kj_per_k``, ``coil_ua_kw_per_k``,
``tau_chw_min``, ``humidity_reference_pct``, ``max_dt_over_tau``) are published guesses, not fitted to any
facility. See docs/PHYSICS_V2.md for units, equations and the list of non-modelled phenomena.

Modes are plain strings ("free_air", "closed_loop", "evaporative", "hybrid") so this module imports nothing from
src/digital_twin.py (which imports it).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields
from typing import Any, Optional

PARAMS_SCHEMA_VERSION = 1
MODES: tuple[str, ...] = ("free_air", "closed_loop", "evaporative", "hybrid")


class PhysicsParamsError(ValueError):
    """A PhysicsParams field is non-finite or outside its physical range."""


@dataclass(frozen=True)
class PhysicsParams:
    # ---- IT load (the existing parametric power curve) ------------------------------------------------
    max_it_power_kw: float = 500.0  # kW at 100 % utilisation
    idle_power_fraction: float = 0.4  # share of max power at 0 % utilisation

    # ---- air path (server inlet/outlet) ----------------------------------------------------------------
    air_flow_base_m3_s: float = 8.0  # airflow at idle
    air_flow_full_load_m3_s: float = 20.0  # airflow at 100 % load; ramps linearly in between
    tau_air_min: float = 10.0  # first-order lag of T_in and T_out [min]
    chw_approach_c: float = 2.0  # supply air = chilled-water supply + approach
    inlet_supply_floor_c: float = 18.0  # CRAH holds supply air at or above this
    free_air_fan_heat_c: float = 1.0  # economiser fans add this to outside air
    free_air_ineffective_above_c: float = 12.0  # free-air mode falls back to hybrid at/above this

    # ---- lumped thermal capacitance and coil (v2) ------------------------------------------------------
    thermal_capacitance_kj_per_k: float = 22500.0  # C_th: room air + equipment + structure   [kJ/K]
    coil_ua_kw_per_k: float = 25.0  # UA: effective conductance room -> heat sink          [kW/K]
    max_dt_over_tau: float = 4.0  # step-size guard: dt <= this x (C_th / UA)

    # ---- chilled-water actuator (rate limit + first-order lag) -----------------------------------------
    chw_rate_limit_c_per_5min: float = 2.0  # max change of the applied setpoint per 300 s
    tau_chw_min: float = 2.0  # first-order lag of the applied setpoint [min]

    # ---- cooling-plant capacity -------------------------------------------------------------------------
    capacity_design_kw: Optional[float] = None  # None -> capacity_margin x max_it_power_kw
    capacity_margin: float = 1.10
    capacity_derate_start_c: float = 35.0  # heat-rejection temperature above which capacity derates
    capacity_derate_per_c: float = 0.01
    capacity_min_fraction: float = 0.2

    # ---- COP (v1 functional form) ------------------------------------------------------------------------
    cop_free_air: float = 8.0
    cop_closed_loop: float = 4.5
    cop_evaporative: float = 3.5
    cop_hybrid: float = 4.0
    cop_load_derate: float = 0.15  # COP loses this fraction at full load
    cop_outside_derate_start_c: float = 20.0
    cop_outside_derate_per_c: float = 0.01
    cop_min: float = 0.5
    cop_chw_reference_c: float = 12.0
    cop_chw_lift_per_c: float = 0.02  # +/- per degC of chilled-water setpoint vs reference (chiller modes)
    cop_chw_bonus_floor: float = 0.5
    cop_humidity_reference_pct: float = 40.0  # evaporative COP derate starts above this RH
    cop_humidity_derate_per_pct: float = 0.005

    # ---- water: evaporated heat, bounded by latent heat -------------------------------------------------
    latent_heat_j_per_kg: float = 2.26e6
    evap_fraction_free_air: float = 0.0  # share of rejected heat that leaves as latent heat, per mode
    evap_fraction_closed_loop: float = 0.8 / 30.0
    evap_fraction_evaporative: float = 0.8
    evap_fraction_hybrid: float = 0.4
    water_warm_reference_c: float = 15.0
    water_warm_factor_per_c: float = 0.02
    humidity_reference_pct: float = 50.0  # RH at which the wet-bulb factors below equal 1 (== v1)
    wet_bulb_factor_min: float = 0.25
    wet_bulb_factor_max: float = 2.0

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PhysicsParamsError(f"{f.name} must be a number, got {value!r}")
            if not math.isfinite(value):
                raise PhysicsParamsError(f"{f.name} must be finite, got {value!r}")
            object.__setattr__(self, f.name, float(value))  # canonical type -> stable hash for 1 vs 1.0

        positive = (
            "max_it_power_kw",
            "air_flow_base_m3_s",
            "air_flow_full_load_m3_s",
            "tau_air_min",
            "thermal_capacitance_kj_per_k",
            "coil_ua_kw_per_k",
            "max_dt_over_tau",
            "tau_chw_min",
            "capacity_margin",
            "latent_heat_j_per_kg",
            "cop_free_air",
            "cop_closed_loop",
            "cop_evaporative",
            "cop_hybrid",
            "cop_min",
            "cop_chw_bonus_floor",
            "wet_bulb_factor_min",
            "wet_bulb_factor_max",
        )
        for name in positive:
            if not getattr(self, name) > 0:
                raise PhysicsParamsError(f"{name} must be > 0, got {getattr(self, name)!r}")
        nonnegative = (
            "chw_rate_limit_c_per_5min",
            "capacity_derate_per_c",
            "cop_outside_derate_per_c",
            "cop_chw_lift_per_c",
            "cop_humidity_derate_per_pct",
            "water_warm_factor_per_c",
            "chw_approach_c",
            "free_air_fan_heat_c",
            "evap_fraction_free_air",
            "evap_fraction_closed_loop",
            "evap_fraction_evaporative",
            "evap_fraction_hybrid",
        )
        for name in nonnegative:
            if getattr(self, name) < 0:
                raise PhysicsParamsError(f"{name} must be >= 0, got {getattr(self, name)!r}")
        for name in ("idle_power_fraction", "cop_load_derate", "capacity_min_fraction"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise PhysicsParamsError(f"{name} must be in [0, 1], got {getattr(self, name)!r}")
        for name in (
            "evap_fraction_free_air",
            "evap_fraction_closed_loop",
            "evap_fraction_evaporative",
            "evap_fraction_hybrid",
        ):
            if getattr(self, name) > 1.0:
                raise PhysicsParamsError(f"{name} must be <= 1, got {getattr(self, name)!r}")
        if not 0.0 <= self.humidity_reference_pct <= 100.0:
            raise PhysicsParamsError("humidity_reference_pct must be in [0, 100]")
        if self.air_flow_full_load_m3_s < self.air_flow_base_m3_s:
            raise PhysicsParamsError("air_flow_full_load_m3_s must be >= air_flow_base_m3_s")
        if self.wet_bulb_factor_min > self.wet_bulb_factor_max:
            raise PhysicsParamsError("wet_bulb_factor_min must be <= wet_bulb_factor_max")
        if self.capacity_design_kw is not None and not self.capacity_design_kw > 0:
            raise PhysicsParamsError(f"capacity_design_kw must be > 0, got {self.capacity_design_kw!r}")

    # ------------------------------------------------------------------------------------------------------
    @property
    def design_capacity_kw(self) -> float:
        """Heat-removal capacity of the plant at reference ambient (kW)."""
        if self.capacity_design_kw is not None:
            return self.capacity_design_kw
        return self.capacity_margin * self.max_it_power_kw

    @property
    def room_time_constant_s(self) -> float:
        """tau_room = C_th / UA [s] (the coil-limited time constant of T_room)."""
        return self.thermal_capacitance_kj_per_k / self.coil_ua_kw_per_k

    def base_cop(self, mode: str) -> float:
        return {
            "free_air": self.cop_free_air,
            "closed_loop": self.cop_closed_loop,
            "evaporative": self.cop_evaporative,
            "hybrid": self.cop_hybrid,
        }[mode]

    def evap_fraction(self, mode: str) -> float:
        return {
            "free_air": self.evap_fraction_free_air,
            "closed_loop": self.evap_fraction_closed_loop,
            "evaporative": self.evap_fraction_evaporative,
            "hybrid": self.evap_fraction_hybrid,
        }[mode]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        payload = {"schema": PARAMS_SCHEMA_VERSION, "params": self.as_dict()}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def params_hash(self) -> str:
        """SHA-256 (hex) of the canonical encoding of every field: the ``physics_params_hash``."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


DEFAULT_PHYSICS_PARAMS = PhysicsParams()
