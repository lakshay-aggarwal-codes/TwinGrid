"""
Digital twin simulation of a data centre using thermodynamic and hydraulic physics.

Provides physics-based models for thermal dynamics, cooling system performance,
water consumption, and rule-based control. Supports an optional Physics-Informed
Neural Network (PINN) for surrogate prediction — patent core combined with the
joint optimizer (J = α·W + β·E + γ·C).

PERFORMANCE NOTE: This module now uses the optimized implementation for
real-time dashboard performance. The original implementation is available
as DigitalTwinOriginal if needed for compatibility testing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .logging_config import log_function_entry, log_function_exit, log_error, log_simulation_step

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


class CoolingMode(str, Enum):
    """Supported cooling modes with distinct COP and water characteristics."""

    FREE_AIR = "free_air"
    CLOSED_LOOP = "closed_loop"
    EVAPORATIVE = "evaporative"
    HYBRID = "hybrid"


# COP and evaporation rate per mode
_COP: dict[CoolingMode, float] = {
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

    All fields align with sensor_data.csv schema for compatibility
    with data pipelines and ML models.
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
        }


class DigitalTwin:
    """
    Physics-based digital twin for data centre thermal and hydraulic simulation.

    Simulates thermodynamic energy balance (Q = ṁ·cp·ΔT), cooling COP by mode,
    and water consumption with evaporation rates. Supports rule-based cooling
    mode selection and scenario runs.
    """

    def __init__(
        self,
        *,
        max_it_power_kw: float = 500.0,
        idle_power_fraction: float = 0.4,
        air_flow_m3_s: float = 8.0,
        initial_cooling_mode: CoolingMode = CoolingMode.CLOSED_LOOP,
        start_time: datetime | None = None,
    ) -> None:
        """
        Initialise the digital twin.

        Args:
            max_it_power_kw: Maximum IT power at 100% utilisation (kW).
            idle_power_fraction: Fraction of max power at 0% utilisation (default 0.4).
            air_flow_m3_s: Air flow rate through servers (m³/s), default 8.0.
            initial_cooling_mode: Starting cooling mode.
            start_time: Simulation start timestamp. Defaults to now.
        """
        log_function_entry(
            "DigitalTwin.__init__",
            max_it_power_kw=max_it_power_kw,
            idle_power_fraction=idle_power_fraction,
            air_flow_m3_s=air_flow_m3_s,
            initial_cooling_mode=initial_cooling_mode,
            start_time=start_time
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
            self._state: DataCentreState = self._build_initial_state()
            self._pinn: Any = None
            
            log_function_exit("DigitalTwin.__init__", result="DigitalTwin initialized successfully")
        except Exception as e:
            log_error("DigitalTwin.__init__", e)
            raise

    def _build_initial_state(self) -> DataCentreState:
        """Build initial state from current parameters."""
        it_power = self.compute_it_power(self._utilisation)
        inlet = max(INLET_TEMP_MIN, self._outside_temp_C - 3.0)
        outlet = self.compute_outlet_temp(inlet, it_power, self._air_flow_m3_s)
        cooling = self.compute_cooling_power(it_power, self._cooling_mode, self._outside_temp_C)
        flow, consumed = self.compute_water_consumption(
            cooling, self._cooling_mode, self._outside_temp_C
        )
        total = it_power + cooling
        pue = total / it_power if it_power > 0.1 else 1.0
        it_energy_kwh = it_power * (INTERVAL_MINUTES / 60)
        wue = consumed / it_energy_kwh if it_energy_kwh > 0.01 else 0.0

        return DataCentreState(
            timestamp=self._time,
            server_utilisation=self._utilisation,
            outside_temp_C=self._outside_temp_C,
            server_inlet_temp_C=inlet,
            server_outlet_temp_C=outlet,
            it_power_kw=it_power,
            cooling_power_kw=cooling,
            total_power_kw=total,
            pue=pue,
            water_flow_lpm=flow,
            water_consumed_L=self._water_consumed_cumulative_L + consumed,
            wue=wue,
            humidity_pct=self._humidity_pct,
            water_pressure_bar=self._water_pressure_bar,
            cooling_mode=self._cooling_mode,
            anomaly=0,
        )

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

    def compute_cooling_power(
        self,
        it_power_kw: float,
        mode: CoolingMode,
        outside_temp_C: float,
    ) -> float:
        """
        Compute cooling system power from IT heat load and COP.

        COP varies by mode. Free-air only effective when outside < 12°C;
        otherwise falls back to hybrid COP for calculation.

        Args:
            it_power_kw: IT power (heat load) in kW.
            mode: Cooling mode.
            outside_temp_C: Outside air temperature (°C).

        Returns:
            Cooling power in kW.
        """
        cop = _COP[mode]
        if mode == CoolingMode.FREE_AIR and outside_temp_C >= 12.0:
            logger.debug(
                "Free-air ineffective when outside >= 12°C (%.1f), using hybrid COP",
                outside_temp_C,
            )
            cop = _COP[CoolingMode.HYBRID]
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

        Free-air uses no water. Other modes scale with cooling load and
        outside temperature (higher temp → more evaporation).

        Args:
            cooling_power_kw: Cooling system power in kW.
            mode: Cooling mode.
            outside_temp_C: Outside air temperature (°C).

        Returns:
            Tuple of (flow_lpm, consumed_L_per_5min).
        """
        if mode == CoolingMode.FREE_AIR:
            return 0.0, 0.0

        evap_rate = _EVAPORATION_RATE[mode]
        if evap_rate <= 0:
            return 0.0, 0.0

        # Consumed scales with cooling load; higher outside temp increases demand
        temp_factor = 1.0 + 0.02 * max(0, outside_temp_C - 15)
        consumed_L = cooling_power_kw * 0.5 * evap_rate * 10 * temp_factor
        consumed_L = max(0, consumed_L)

        # flow_lpm such that flow * 5_min * evap_rate = consumed
        flow_lpm = consumed_L / (INTERVAL_MINUTES * evap_rate) if evap_rate > 0 else 0.0

        return flow_lpm, consumed_L

    # -------------------------------------------------------------------------
    # Control methods
    # -------------------------------------------------------------------------

    def select_cooling_mode(
        self,
        outside_temp_C: float,
        water_stress: float,
    ) -> CoolingMode:
        """
        Rule-based cooling mode selection.

        - Free-air when outside < 12°C (no water, high COP).
        - Closed-loop when water stress high (lowest evaporation).
        - Evaporative when outside hot and water stress low.
        - Hybrid as default balance.

        Args:
            outside_temp_C: Outside air temperature (°C).
            water_stress: Water stress indicator in [0, 1], 1 = critical.

        Returns:
            Selected CoolingMode.
        """
        if outside_temp_C < 12.0:
            mode = CoolingMode.FREE_AIR
            logger.debug("Selected free_air (outside %.1f < 12°C)", outside_temp_C)
        elif water_stress > 0.7:
            mode = CoolingMode.CLOSED_LOOP
            logger.debug("Selected closed_loop (water_stress %.2f > 0.7)", water_stress)
        elif outside_temp_C > 28.0 and water_stress < 0.3:
            mode = CoolingMode.EVAPORATIVE
            logger.debug("Selected evaporative (hot, low water stress)")
        else:
            mode = CoolingMode.HYBRID
            logger.debug("Selected hybrid (default)")

        return mode

    def step(self, action_dict: dict[str, Any]) -> DataCentreState:
        """
        Advance simulation by 5 minutes.

        Expected keys: utilisation, outside_temp_C, cooling_mode (optional),
        humidity_pct (optional), water_pressure_bar (optional).

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

            self._time += timedelta(minutes=INTERVAL_MINUTES)

            # Compute state
            it_power = self.compute_it_power(self._utilisation)
            cooling = self.compute_cooling_power(it_power, self._cooling_mode, self._outside_temp_C)
            flow, consumed = self.compute_water_consumption(
                cooling, self._cooling_mode, self._outside_temp_C
            )
            self._water_consumed_cumulative_L += consumed

            inlet = max(INLET_TEMP_MIN, min(INLET_TEMP_MAX, self._outside_temp_C - 3.0))
            outlet = self.compute_outlet_temp(inlet, it_power, self._air_flow_m3_s)
            outlet = min(outlet, OUTLET_TEMP_MAX + 5)  # Allow slight overshoot for realism

            total = it_power + cooling
            pue = total / it_power if it_power > 0.1 else 1.0
            it_energy_kwh = it_power * (INTERVAL_MINUTES / 60)
            wue = consumed / it_energy_kwh if it_energy_kwh > 0.01 else 0.0

            self._state = DataCentreState(
                timestamp=self._time,
                server_utilisation=self._utilisation,
                outside_temp_C=self._outside_temp_C,
                server_inlet_temp_C=inlet,
                server_outlet_temp_C=outlet,
                it_power_kw=it_power,
                cooling_power_kw=cooling,
                total_power_kw=total,
                pue=pue,
                water_flow_lpm=flow,
                water_consumed_L=self._water_consumed_cumulative_L,
                wue=wue,
                humidity_pct=self._humidity_pct,
                water_pressure_bar=self._water_pressure_bar,
                cooling_mode=self._cooling_mode,
                anomaly=0,
            )
            
            # Log simulation step results
            log_simulation_step(
                step_number=int((self._time - (self._time - timedelta(minutes=INTERVAL_MINUTES))).total_seconds() / 60),
                utilisation=self._utilisation,
                outside_temp_C=self._outside_temp_C,
                inlet_temp_C=inlet,
                outlet_temp_C=outlet,
                it_power_kw=it_power,
                cooling_power_kw=cooling,
                total_power_kw=total,
                pue=pue,
                water_flow_lpm=flow,
                water_consumed_L=consumed,
                wue=wue,
                cooling_mode=self._cooling_mode.value
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
