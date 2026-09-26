"""
Digital twin simulation of a data centre using thermodynamic and hydraulic physics.

Provides physics-based models for thermal dynamics, cooling system performance,
water consumption, and rule-based control. Supports an optional Physics-Informed
Neural Network (PINN) for surrogate prediction — patent core combined with the
joint optimizer (J = α·W + β·E + γ·C).

DYNAMIC PHYSICS: thermal state has memory (first-order lag toward a
steady-state target using a thermal time constant), and the chilled-water
actuator is rate-limited. There is a deterministic requested->applied
control pipeline that runs BEFORE physics, so the mode/temperature actually
used for computation is always the same one reported back in the state.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .carbon_provider import load_diurnal_carbon_intensity
from .logging_config import log_error, log_function_entry, log_function_exit, log_simulation_step

# Matches DataCentreEnv.DROUGHT_THRESHOLD (src/optimizer.py) exactly --
# both files enforce the same patent Claim 3 rule.
DROUGHT_THRESHOLD = 0.7

logger = logging.getLogger(__name__)

# Physical constants (SI units)
SPECIFIC_HEAT_AIR_J_KG_K: float = 1005.0  # J/(kg·K)
AIR_DENSITY_KG_M3: float = 1.2  # kg/m³
INTERVAL_MINUTES: int = 5

# ASHRAE operating limits (°C)
INLET_TEMP_MIN: float = 18.0
INLET_TEMP_MAX: float = 27.0
OUTLET_TEMP_MAX: float = 45.0
PUE_MAX_SAFE: float = 2.0

# Dynamic-physics tuning constants
FREE_AIR_INEFFECTIVE_OUTSIDE_TEMP_C: float = 12.0
DEFAULT_THERMAL_TIME_CONSTANT_MIN: float = 10.0
DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP: float = 2.0
DEFAULT_CHILLED_WATER_TEMP_C: float = 12.0
CHILLED_WATER_APPROACH_C: float = 2.0  # inlet ≈ chilled water supply + approach
FREE_AIR_OFFSET_C: float = 2.0  # inlet ≈ outside temp - offset, in free-air mode
COP_LOAD_DERATE: float = 0.15  # COP loses up to 15% at full load
COP_OUTSIDE_TEMP_DERATE_PER_C: float = 0.01  # per °C above 20°C
COP_MIN: float = 0.5
# A warmer chilled-water setpoint means less compressor lift (smaller gap to
# the condenser/outside side), so it takes less compressor work per kW of
# heat rejected -- i.e. higher COP. Only applies to modes that actually run
# a chiller against this setpoint (CLOSED_LOOP, HYBRID); FREE_AIR and
# EVAPORATIVE reject heat without a compressor lift to this setpoint at all.
# Reference point is DEFAULT_CHILLED_WATER_TEMP_C, so omitting the setpoint
# (or passing exactly the default) reproduces the previous, setpoint-blind
# COP exactly -- this is an additive, backward-compatible physics term.
COP_CHILLED_WATER_LIFT_DERATE_PER_C: float = 0.02  # +/-2% COP per °C vs default
WATER_FLOW_SCALE_LPM_PER_KW: float = 30.0
WATER_TEMP_FACTOR_PER_C: float = 0.02
WATER_HUMIDITY_FACTOR_PER_PCT: float = 0.01
EVAPORATIVE_HUMIDITY_REFERENCE_PCT: float = 40.0


class CoolingMode(str, Enum):
    """Supported cooling modes with distinct COP and water characteristics."""

    FREE_AIR = "free_air"
    CLOSED_LOOP = "closed_loop"
    EVAPORATIVE = "evaporative"
    HYBRID = "hybrid"


# Nominal (pre-derate) COP and evaporation rate per mode
_BASE_COP: dict[CoolingMode, float] = {
    CoolingMode.FREE_AIR: 8.0,
    CoolingMode.CLOSED_LOOP: 4.5,
    CoolingMode.EVAPORATIVE: 3.5,
    CoolingMode.HYBRID: 4.0,
}
_EVAPORATION_RATE: dict[CoolingMode, float] = {
    CoolingMode.FREE_AIR: 0.0,
    CoolingMode.CLOSED_LOOP: 0.001,
    CoolingMode.EVAPORATIVE: 0.03,
    CoolingMode.HYBRID: 0.015,
}


@dataclass
class DataCentreState:
    """
    Complete snapshot of data centre sensor state.

    All fields align with sensor_data.csv schema for compatibility with
    data pipelines and ML models. `cooling_mode` here is always the mode
    PHYSICS ACTUALLY USED this step (the "applied" mode), not necessarily
    the mode requested.
    """

    timestamp: datetime
    server_utilisation: float
    outside_temp_C: float
    server_inlet_temp_C: float
    server_outlet_temp_C: float
    it_power_kw: float
    cooling_power_kw: float
    total_power_kw: float
    pue: float
    water_flow_lpm: float
    water_consumed_L: float
    wue: float
    humidity_pct: float
    water_pressure_bar: float
    cooling_mode: CoolingMode
    anomaly: int = 0
    water_stress: float = 0.0
    carbon_intensity_gco2_per_kwh: float = 0.0
    carbon_gco2: float = 0.0
    drought_override_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for DataFrame construction."""
        return {
            "timestamp": self.timestamp,
            "server_utilisation": self.server_utilisation,
            "outside_temp_C": self.outside_temp_C,
            "server_inlet_temp_C": self.server_inlet_temp_C,
            "server_outlet_temp_C": self.server_outlet_temp_C,
            "it_power_kw": self.it_power_kw,
            "cooling_power_kw": self.cooling_power_kw,
            "total_power_kw": self.total_power_kw,
            "pue": self.pue,
            "water_flow_lpm": self.water_flow_lpm,
            "water_consumed_L": self.water_consumed_L,
            "wue": self.wue,
            "humidity_pct": self.humidity_pct,
            "water_pressure_bar": self.water_pressure_bar,
            "cooling_mode": self.cooling_mode.value,
            "anomaly": self.anomaly,
            "water_stress": self.water_stress,
            "carbon_intensity_gco2_per_kwh": self.carbon_intensity_gco2_per_kwh,
            "carbon_gco2": self.carbon_gco2,
            "drought_override_active": self.drought_override_active,
        }


class DigitalTwin:
    """
    Physics-based digital twin for data centre thermal and hydraulic simulation.

    Simulates thermodynamic energy balance (Q = ṁ·cp·ΔT) with first-order
    thermal lag, dynamic COP by mode/load/outside-temp/humidity, a
    rate-limited chilled-water actuator, and water consumption with
    evaporation rates. Supports rule-based cooling mode selection and
    scenario runs.
    """

    def __init__(
        self,
        *,
        max_it_power_kw: float = 500.0,
        idle_power_fraction: float = 0.4,
        air_flow_m3_s: float = 8.0,
        initial_cooling_mode: CoolingMode = CoolingMode.CLOSED_LOOP,
        start_time: datetime | None = None,
        thermal_time_constant_min: float = DEFAULT_THERMAL_TIME_CONSTANT_MIN,
        max_chilled_water_rate_C_per_step: float = DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP,
        initial_chilled_water_temp_C: float = DEFAULT_CHILLED_WATER_TEMP_C,
    ) -> None:
        """
        Initialise the digital twin.

        Args:
            max_it_power_kw: Maximum IT power at 100% utilisation (kW).
            idle_power_fraction: Fraction of max power at 0% utilisation (default 0.4).
            air_flow_m3_s: Air flow rate through servers (m³/s), default 8.0.
            initial_cooling_mode: Starting (requested) cooling mode.
            start_time: Simulation start timestamp. Defaults to now.
            thermal_time_constant_min: First-order thermal lag time constant (minutes).
            max_chilled_water_rate_C_per_step: Max chilled-water setpoint change per step (°C).
            initial_chilled_water_temp_C: Starting chilled-water supply temperature (°C).
        """
        log_function_entry(
            "DigitalTwin.__init__",
            max_it_power_kw=max_it_power_kw,
            idle_power_fraction=idle_power_fraction,
            air_flow_m3_s=air_flow_m3_s,
            initial_cooling_mode=initial_cooling_mode,
            start_time=start_time,
        )

        try:
            self._max_it_power_kw = max_it_power_kw
            self._idle_power_fraction = idle_power_fraction
            self._air_flow_m3_s = air_flow_m3_s
            self._cooling_mode = initial_cooling_mode
            self._time = start_time or datetime.now()
            self._utilisation: float = 0.0
            self._outside_temp_C: float = 25.0
            self._water_consumed_cumulative_L: float = 0.0
            self._humidity_pct: float = 50.0
            self._water_pressure_bar: float = 3.0
            self._water_stress: float = 0.0
            # is_real is False when data/cleaned/carbon_intensity.csv is absent and the flat
            # 475 gCO2/kWh fallback is in use; surfaced via carbon_data_is_real so the UI
            # never presents the fallback as real grid data.
            self._carbon_intensity_by_hour, self.carbon_data_is_real = load_diurnal_carbon_intensity()

            # Dynamic-physics state
            self._thermal_time_constant_min = thermal_time_constant_min
            self._max_chilled_water_rate_C_per_step = max_chilled_water_rate_C_per_step
            self._requested_chilled_water_temp_C = initial_chilled_water_temp_C
            self._applied_chilled_water_temp_C = initial_chilled_water_temp_C
            self._inlet_temp_C: float | None = None
            self._outlet_temp_C: float | None = None

            self._state: DataCentreState = self._build_initial_state()
            self._pinn: Any = None

            log_function_exit("DigitalTwin.__init__", result="DigitalTwin initialized successfully")
        except Exception as e:
            log_error("DigitalTwin.__init__", e)
            raise

    # -------------------------------------------------------------------------
    # Requested -> applied control pipeline (runs BEFORE physics)
    # -------------------------------------------------------------------------

    def _determine_applied_cooling_mode(
        self, requested_mode: CoolingMode, outside_temp_C: float
    ) -> CoolingMode:
        """
        Resolve the mode physics will actually use this step.

        Free-air is only physically effective when outside air is cold
        enough; otherwise the system falls back to hybrid. This is the
        ONLY place mode substitution happens, and the result is what gets
        reported in DataCentreState.cooling_mode (fixes the previous defect
        where FREE_AIR could be reported while HYBRID's COP was silently
        used for the actual calculation).
        """
        if requested_mode == CoolingMode.FREE_AIR and outside_temp_C >= FREE_AIR_INEFFECTIVE_OUTSIDE_TEMP_C:
            logger.debug(
                "Free-air ineffective when outside >= %.1f°C (%.1f), applying hybrid",
                FREE_AIR_INEFFECTIVE_OUTSIDE_TEMP_C,
                outside_temp_C,
            )
            return CoolingMode.HYBRID
        return requested_mode

    def _determine_applied_chilled_water_temp_C(self, requested_C: float) -> float:
        """Rate-limit the chilled-water setpoint toward the requested value."""
        delta = requested_C - self._applied_chilled_water_temp_C
        max_step = self._max_chilled_water_rate_C_per_step
        bounded_delta = max(-max_step, min(max_step, delta))
        return self._applied_chilled_water_temp_C + bounded_delta

    # -------------------------------------------------------------------------
    # Thermodynamic methods
    # -------------------------------------------------------------------------

    def compute_it_power(self, utilisation: float) -> float:
        """
        Compute IT power from server utilisation with idle fraction 0.4.

        Power = idle_power + (1 - idle_frac) * utilisation * max_power.

        Args:
            utilisation: Server utilisation in [0, 1].

        Returns:
            IT power in kW.

        Raises:
            ValueError: If utilisation not in [0, 1].
        """
        log_function_entry("DigitalTwin.compute_it_power", utilisation=utilisation)

        try:
            if not 0 <= utilisation <= 1:
                error_msg = f"Utilisation must be in [0, 1], got {utilisation}"
                log_error("DigitalTwin.compute_it_power", ValueError(error_msg))
                raise ValueError(error_msg)

            idle = self._idle_power_fraction * self._max_it_power_kw
            result = idle + (1 - self._idle_power_fraction) * utilisation * self._max_it_power_kw

            log_function_exit("DigitalTwin.compute_it_power", result=result)
            return result
        except Exception as e:
            log_error("DigitalTwin.compute_it_power", e)
            raise

    def compute_outlet_temp(
        self,
        inlet_temp_C: float,
        it_power_kw: float,
        airflow_m3_s: float = 8.0,
    ) -> float:
        """
        Compute server outlet temperature from energy balance: Q = ṁ·cp·ΔT.

        ΔT = IT_power_W / (ρ · V̇ · cp).

        Args:
            inlet_temp_C: Server inlet air temperature (°C).
            it_power_kw: IT power in kW.
            airflow_m3_s: Air flow rate (m³/s), default 8.0.

        Returns:
            Outlet temperature in °C.
        """
        if it_power_kw <= 0:
            return inlet_temp_C
        heat_w = it_power_kw * 1000.0
        m_dot = AIR_DENSITY_KG_M3 * airflow_m3_s
        denom = m_dot * SPECIFIC_HEAT_AIR_J_KG_K
        delta_t = heat_w / denom if denom > 0 else 0.0
        return inlet_temp_C + delta_t

    def _effective_cop(
        self,
        mode: CoolingMode,
        it_power_kw: float,
        outside_temp_C: float,
        chilled_water_temp_C: float | None = None,
    ) -> float:
        """
        Derate the nominal per-mode COP by load fraction, outside temperature,
        (for evaporative) humidity, and (for CLOSED_LOOP/HYBRID) the chilled-
        water setpoint's compressor lift. Never substitutes modes — mode
        substitution happens once, earlier, in `_determine_applied_cooling_mode`.
        """
        base_cop = _BASE_COP[mode]

        load_fraction = 0.0
        if self._max_it_power_kw > 0:
            load_fraction = max(0.0, min(1.0, it_power_kw / self._max_it_power_kw))
        load_penalty = 1.0 - COP_LOAD_DERATE * load_fraction

        outside_penalty = 1.0 - COP_OUTSIDE_TEMP_DERATE_PER_C * max(0.0, outside_temp_C - 20.0)

        humidity_penalty = 1.0
        if mode == CoolingMode.EVAPORATIVE:
            humidity_penalty = 1.0 - 0.5 * WATER_HUMIDITY_FACTOR_PER_PCT * max(
                0.0, self._humidity_pct - EVAPORATIVE_HUMIDITY_REFERENCE_PCT
            )

        # Chilled-water lift term: only the modes that actually run a chiller
        # against this setpoint (CLOSED_LOOP, HYBRID) benefit from a warmer
        # setpoint. Omitting chilled_water_temp_C -- or passing exactly
        # DEFAULT_CHILLED_WATER_TEMP_C -- gives a bonus of 1.0, i.e. the
        # pre-existing setpoint-blind COP is preserved exactly.
        water_temp_bonus = 1.0
        if chilled_water_temp_C is not None and mode in (CoolingMode.CLOSED_LOOP, CoolingMode.HYBRID):
            water_temp_bonus = 1.0 + COP_CHILLED_WATER_LIFT_DERATE_PER_C * (
                chilled_water_temp_C - DEFAULT_CHILLED_WATER_TEMP_C
            )
            water_temp_bonus = max(0.5, water_temp_bonus)  # floor: never let a cold setpoint collapse/invert COP

        cop = base_cop * load_penalty * outside_penalty * humidity_penalty * water_temp_bonus
        return max(cop, COP_MIN)

    def compute_cooling_power(
        self,
        it_power_kw: float,
        mode: CoolingMode,
        outside_temp_C: float,
        chilled_water_temp_C: float | None = None,
    ) -> float:
        """
        Compute cooling system power from IT heat load and dynamic COP.

        COP is derated by load fraction, outside temperature, (for
        evaporative mode) current humidity, and -- when chilled_water_temp_C
        is supplied, for CLOSED_LOOP/HYBRID modes -- the compressor lift
        implied by the chilled-water setpoint. It is never a fixed per-mode
        constant. This method never substitutes modes internally; mode
        substitution is resolved once, earlier in the pipeline, by
        `_determine_applied_cooling_mode`, and `mode` here is always the
        already-resolved applied mode.

        Args:
            it_power_kw: IT power (heat load) in kW.
            mode: Cooling mode (already resolved/applied).
            outside_temp_C: Outside air temperature (°C).
            chilled_water_temp_C: Applied chilled-water setpoint (°C), if the
                caller has one available. Optional and backward-compatible:
                omitting it reproduces the previous setpoint-blind COP.

        Returns:
            Cooling power in kW.
        """
        cop = self._effective_cop(mode, it_power_kw, outside_temp_C, chilled_water_temp_C)
        return it_power_kw / cop if cop > 0 else 0.0

    # -------------------------------------------------------------------------
    # Hydraulic methods
    # -------------------------------------------------------------------------

    def compute_water_consumption(
        self,
        cooling_power_kw: float,
        mode: CoolingMode,
        outside_temp_C: float,
    ) -> tuple[float, float]:
        """
        Compute water flow and consumption for the cooling mode.

        `flow_lpm` is computed FIRST as a function of cooling load, mode,
        outside temperature and (for evaporative mode) current humidity;
        `consumed_L` is then derived as `flow_lpm * INTERVAL_MINUTES` — this
        is a one-way, non-circular derivation (flow never derived FROM
        consumed). Free-air uses no water.

        Args:
            cooling_power_kw: Cooling system power in kW.
            mode: Cooling mode.
            outside_temp_C: Outside air temperature (°C).

        Returns:
            Tuple of (flow_lpm, consumed_L_per_interval).
        """
        if mode == CoolingMode.FREE_AIR:
            return 0.0, 0.0

        evap_rate = _EVAPORATION_RATE[mode]
        if evap_rate <= 0:
            return 0.0, 0.0

        # Higher outside temp increases evaporative demand.
        temp_factor = 1.0 + WATER_TEMP_FACTOR_PER_C * max(0.0, outside_temp_C - 15.0)

        # Higher ambient humidity makes evaporative cooling less effective,
        # so more flow is needed for the same cooling effect.
        humidity_factor = 1.0
        if mode == CoolingMode.EVAPORATIVE:
            humidity_factor = 1.0 + WATER_HUMIDITY_FACTOR_PER_PCT * max(
                0.0, self._humidity_pct - EVAPORATIVE_HUMIDITY_REFERENCE_PCT
            )

        flow_lpm = cooling_power_kw * evap_rate * WATER_FLOW_SCALE_LPM_PER_KW * temp_factor * humidity_factor
        flow_lpm = max(0.0, flow_lpm)
        consumed_L = flow_lpm * INTERVAL_MINUTES

        return flow_lpm, consumed_L

    # -------------------------------------------------------------------------
    # Control methods
    # -------------------------------------------------------------------------

    def _compute_carbon(self, cooling_power_kw: float) -> tuple[float, float]:
        """Returns (carbon_intensity_gco2_per_kwh, carbon_gco2) for the
        current hour, using the same real diurnal curve as DataCentreEnv
        (src/optimizer.py) -- see src/carbon_provider.py. Unchanged from
        the pre-dynamic-physics implementation.
        """
        intensity = float(self._carbon_intensity_by_hour[self._time.hour])
        carbon_gco2 = cooling_power_kw * intensity * (INTERVAL_MINUTES / 60)
        return intensity, carbon_gco2

    def select_cooling_mode(
        self,
        outside_temp_C: float,
        water_stress: float,
    ) -> CoolingMode:
        """
        Rule-based cooling mode selection.

        - Closed-loop when water stress > DROUGHT_THRESHOLD (patent Claim 3
          drought override — checked first; must match DataCentreEnv's threshold).
        - Free-air when outside < 12°C (no water, high COP).
        - Evaporative when outside hot and water stress low.
        - Hybrid as default balance.

        Args:
            outside_temp_C: Outside air temperature (°C).
            water_stress: Water stress indicator in [0, 1], 1 = critical.

        Returns:
            Selected CoolingMode.
        """
        # Drought override FIRST (patent Claim 3): it must win over every other
        # rule, including free-air, exactly as DataCentreEnv._action_to_control
        # does. (It was previously checked second, so a cold day with severe
        # water stress returned free_air while the state still reported
        # drought_override_active=True.)
        if water_stress > DROUGHT_THRESHOLD:
            mode = CoolingMode.CLOSED_LOOP
            logger.debug("Selected closed_loop (water_stress %.2f > %.2f)", water_stress, DROUGHT_THRESHOLD)
        elif outside_temp_C < 12.0:
            mode = CoolingMode.FREE_AIR
            logger.debug("Selected free_air (outside %.1f < 12°C)", outside_temp_C)
        elif outside_temp_C > 28.0 and water_stress < 0.3:
            mode = CoolingMode.EVAPORATIVE
            logger.debug("Selected evaporative (hot, low water stress)")
        else:
            mode = CoolingMode.HYBRID
            logger.debug("Selected hybrid (default)")

        return mode

    # -------------------------------------------------------------------------
    # Shared transition logic (used by both _build_initial_state and step)
    # -------------------------------------------------------------------------

    def _compute_transition(self, *, persist_cumulative_water: bool = True) -> DataCentreState:
        """
        Compute the next DataCentreState from current internal parameters.

        This is the SOLE place physics/thermal-lag/actuator math happens —
        `_build_initial_state()` (t=0) and `step()` (t>0) both call this,
        so there is exactly one formula for the transition, not two.

        `persist_cumulative_water=False` is used only by
        `_build_initial_state()`, matching the original implementation's
        contract that the cumulative water counter reads exactly 0.0
        immediately after construction (before any `step()` call) even
        though the initial state's own `water_consumed_L` field reflects
        that first instant's consumption.
        """
        # 1. Requested -> applied pipeline (before physics).
        applied_mode = self._determine_applied_cooling_mode(self._cooling_mode, self._outside_temp_C)
        applied_chilled_water_C = self._determine_applied_chilled_water_temp_C(
            self._requested_chilled_water_temp_C
        )
        self._applied_chilled_water_temp_C = applied_chilled_water_C

        # 2. IT power (from current utilisation).
        it_power = self.compute_it_power(self._utilisation)

        # 3. Steady-state thermal targets for this step's applied conditions.
        if applied_mode == CoolingMode.FREE_AIR:
            target_inlet_C = self._outside_temp_C - FREE_AIR_OFFSET_C
        else:
            target_inlet_C = applied_chilled_water_C + CHILLED_WATER_APPROACH_C
        target_outlet_C = self.compute_outlet_temp(target_inlet_C, it_power, self._air_flow_m3_s)

        # 4. First-order lag toward the targets (thermal inertia). At the
        #    very first call (prev is None) the twin starts already at the
        #    steady state, matching a system that has been idle/settled.
        response_factor = 1.0 - math.exp(-INTERVAL_MINUTES / self._thermal_time_constant_min)
        prev_inlet_C = self._inlet_temp_C if self._inlet_temp_C is not None else target_inlet_C
        prev_outlet_C = self._outlet_temp_C if self._outlet_temp_C is not None else target_outlet_C

        new_inlet_C = prev_inlet_C + response_factor * (target_inlet_C - prev_inlet_C)
        new_outlet_C = prev_outlet_C + response_factor * (target_outlet_C - prev_outlet_C)

        # No cosmetic clamping of the ACHIEVED temperatures here — is_safe()
        # must be able to genuinely observe an unsafe state if one occurs.
        self._inlet_temp_C = new_inlet_C
        self._outlet_temp_C = new_outlet_C

        # 5. Cooling power via dynamic COP, using the applied mode and the
        #    applied chilled-water setpoint (compressor-lift term above).
        cooling = self.compute_cooling_power(
            it_power, applied_mode, self._outside_temp_C, chilled_water_temp_C=applied_chilled_water_C
        )

        # 6. Water: flow computed first, consumed derived from flow (never
        #    the reverse).
        flow_lpm, consumed_L = self.compute_water_consumption(cooling, applied_mode, self._outside_temp_C)
        if persist_cumulative_water:
            self._water_consumed_cumulative_L += consumed_L
            cumulative_water_L = self._water_consumed_cumulative_L
        else:
            cumulative_water_L = self._water_consumed_cumulative_L + consumed_L

        total = it_power + cooling
        pue = total / it_power if it_power > 0.1 else 1.0
        it_energy_kwh = it_power * (INTERVAL_MINUTES / 60)
        wue = consumed_L / it_energy_kwh if it_energy_kwh > 0.01 else 0.0
        carbon_intensity, carbon_gco2 = self._compute_carbon(cooling)

        return DataCentreState(
            timestamp=self._time,
            server_utilisation=self._utilisation,
            outside_temp_C=self._outside_temp_C,
            server_inlet_temp_C=new_inlet_C,
            server_outlet_temp_C=new_outlet_C,
            it_power_kw=it_power,
            cooling_power_kw=cooling,
            total_power_kw=total,
            pue=pue,
            water_flow_lpm=flow_lpm,
            water_consumed_L=cumulative_water_L,
            wue=wue,
            humidity_pct=self._humidity_pct,
            water_pressure_bar=self._water_pressure_bar,
            cooling_mode=applied_mode,
            anomaly=0,
            water_stress=self._water_stress,
            carbon_intensity_gco2_per_kwh=carbon_intensity,
            carbon_gco2=carbon_gco2,
            drought_override_active=self._water_stress > DROUGHT_THRESHOLD,
        )

    def _build_initial_state(self) -> DataCentreState:
        """Build initial state (t=0) via the shared transition function."""
        return self._compute_transition(persist_cumulative_water=False)

    def step(self, action_dict: dict[str, Any]) -> DataCentreState:
        """
        Advance simulation by 5 minutes.

        Expected keys: utilisation, outside_temp_C, cooling_mode (optional),
        humidity_pct (optional), water_pressure_bar (optional), water_stress
        (optional), chilled_water_temp_C (optional, new — requested
        chilled-water supply setpoint; rate-limited before it takes effect).

        Args:
            action_dict: Control actions for this step.

        Returns:
            New DataCentreState after the step.
        """
        log_function_entry("DigitalTwin.step", action_dict=action_dict)

        try:
            if "utilisation" in action_dict:
                u = float(action_dict["utilisation"])
                if not 0 <= u <= 1:
                    error_msg = f"utilisation must be in [0, 1], got {u}"
                    log_error("DigitalTwin.step", ValueError(error_msg))
                    raise ValueError(error_msg)
                self._utilisation = u

            if "outside_temp_C" in action_dict:
                self._outside_temp_C = float(action_dict["outside_temp_C"])

            if "cooling_mode" in action_dict:
                m = action_dict["cooling_mode"]
                self._cooling_mode = CoolingMode(m) if isinstance(m, str) else m

            if "humidity_pct" in action_dict:
                self._humidity_pct = float(action_dict["humidity_pct"])

            if "water_pressure_bar" in action_dict:
                self._water_pressure_bar = float(action_dict["water_pressure_bar"])

            if "water_stress" in action_dict:
                self._water_stress = float(action_dict["water_stress"])

            if "chilled_water_temp_C" in action_dict:
                self._requested_chilled_water_temp_C = float(action_dict["chilled_water_temp_C"])

            self._time += timedelta(minutes=INTERVAL_MINUTES)

            self._state = self._compute_transition()

            log_simulation_step(
                step_number=int(INTERVAL_MINUTES),
                utilisation=self._utilisation,
                outside_temp_C=self._outside_temp_C,
                inlet_temp_C=self._state.server_inlet_temp_C,
                outlet_temp_C=self._state.server_outlet_temp_C,
                it_power_kw=self._state.it_power_kw,
                cooling_power_kw=self._state.cooling_power_kw,
                total_power_kw=self._state.total_power_kw,
                pue=self._state.pue,
                water_flow_lpm=self._state.water_flow_lpm,
                water_consumed_L=self._state.water_consumed_L,
                wue=self._state.wue,
                cooling_mode=self._state.cooling_mode.value,
            )

            log_function_exit("DigitalTwin.step", result=f"State updated at {self._time}")
            return self._state
        except Exception as e:
            log_error("DigitalTwin.step", e)
            raise

    def is_safe(self) -> bool:
        """
        Check temperature and PUE constraints.

        Returns:
            True if inlet 18–27°C, outlet ≤ 45°C, and PUE ≤ 2.0.
        """
        s = self._state
        ok_temp = (
            INLET_TEMP_MIN <= s.server_inlet_temp_C <= INLET_TEMP_MAX
            and s.server_outlet_temp_C <= OUTLET_TEMP_MAX
        )
        ok_pue = s.pue <= PUE_MAX_SAFE
        return bool(ok_temp and ok_pue)

    # -------------------------------------------------------------------------
    # Simulation
    # -------------------------------------------------------------------------

    def run_scenario(
        self,
        n_steps: int,
        util_profile: list[float] | Callable[[int], float],
        temp_profile: list[float] | Callable[[int], float],
        *,
        use_auto_cooling: bool = False,
        water_stress: float = 0.0,
    ) -> pd.DataFrame:
        """
        Run a scenario and return a DataFrame of states.

        Args:
            n_steps: Number of 5-minute steps.
            util_profile: Utilisation per step (list or callable(step) -> float).
            temp_profile: Outside temp per step (list or callable(step) -> float).
            use_auto_cooling: If True, use select_cooling_mode each step.
            water_stress: Water stress for auto cooling (0–1).

        Returns:
            DataFrame with one row per step (all sensor fields).
        """
        rows: list[dict[str, Any]] = []

        for i in range(n_steps):
            util = util_profile[i] if isinstance(util_profile, list) else util_profile(i)
            temp = temp_profile[i] if isinstance(temp_profile, list) else temp_profile(i)

            action: dict[str, Any] = {
                "utilisation": util,
                "outside_temp_C": temp,
            }
            if use_auto_cooling:
                action["cooling_mode"] = self.select_cooling_mode(temp, water_stress)

            state = self.step(action)
            rows.append(state.to_dict())

        df = pd.DataFrame(rows)
        logger.info("Scenario complete: %d steps, %d rows", n_steps, len(df))
        return df

    @property
    def state(self) -> DataCentreState:
        """Current data centre state."""
        return self._state

    # -------------------------------------------------------------------------
    # Physics-Informed Neural Network (PINN) — patent core
    # -------------------------------------------------------------------------

    def train_pinn(
        self,
        n_samples: int = 2000,
        epochs: int = 100,
        physics_weight: float = 0.1,
        seed: int | None = None,
    ) -> Any:
        """
        Train the optional Physics-Informed Neural Network on twin rollouts.

        PATENT: PINN learns outlet_temp, water_consumed, PUE with soft physics
        constraints (energy balance, PUE identity, WUE identity). Combines with
        the joint optimizer for surrogate prediction.
        """
        from src.pinn import PhysicsInformedNN, generate_training_data_from_twin

        x, y = generate_training_data_from_twin(self, n_samples=n_samples, seed=seed)
        self._pinn = PhysicsInformedNN(physics_weight=physics_weight)
        self._pinn.fit(x, y, epochs=epochs, verbose=1)
        logger.info("PINN trained on %d samples", n_samples)
        return self._pinn

    def predict_with_pinn(
        self,
        utilisation: float,
        outside_temp_C: float,
        cooling_mode: CoolingMode | str,
        chilled_water_temp_C: float,
    ) -> dict[str, float] | None:
        """
        Predict outlet_temp, water_consumed_L, pue using the PINN if trained.

        Returns None if PINN not available.
        """
        if not hasattr(self, "_pinn") or self._pinn is None:
            return None
        from src.pinn import encode_cooling_mode

        mode_enc = encode_cooling_mode(cooling_mode)
        out = self._pinn.predict(
            np.array([utilisation], dtype=np.float32),
            np.array([outside_temp_C], dtype=np.float32),
            np.array([mode_enc], dtype=np.float32),
            np.array([chilled_water_temp_C], dtype=np.float32),
        )
        return {
            "outlet_temp_C": float(out[0, 0]),
            "water_consumed_L": float(out[0, 1]),
            "pue": float(out[0, 2]),
        }

    def save_pinn(self, path: str | Path) -> None:
        """Save trained PINN weights."""
        if not hasattr(self, "_pinn") or self._pinn is None:
            raise RuntimeError("No PINN trained. Call train_pinn() first.")
        self._pinn.save(path)

    def load_pinn(self, path: str | Path) -> None:
        """Load PINN weights."""
        from src.pinn import PhysicsInformedNN

        if not hasattr(self, "_pinn") or self._pinn is None:
            self._pinn = PhysicsInformedNN()
        self._pinn.load(path)