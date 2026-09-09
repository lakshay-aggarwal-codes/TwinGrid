"""
Generate 90 days of synthetic data centre sensor data with physics-based models.

Output: data/raw/sensor_data.csv with timestamp, utilisation, temperatures,
power metrics, water metrics, and anomaly labels.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .logging_config import log_function_entry, log_function_exit, log_error

logger = logging.getLogger(__name__)

# Physics constants
AIR_DENSITY_KG_M3 = 1.2
SPECIFIC_HEAT_AIR_J_KG_K = 1005.0
COP_EVAPORATIVE = 3.5
EVAPORATION_RATE = 0.03
AIRFLOW_M3_S = 50.0
MAX_IT_POWER_KW = 500.0
INTERVAL_MINUTES = 5


def _compute_utilisation(dt: pd.DatetimeIndex) -> np.ndarray:
    """
    Daily utilisation: 0.4 + 0.5*sin((hour-6)*π/12) clipped to [0, 1].
    Weekend factor: 0.6x on Saturday/Sunday.
    """
    hour = dt.hour + dt.minute / 60
    u_base = 0.4 + 0.5 * np.sin((hour - 6) * np.pi / 12)
    u_base = np.clip(u_base, 0.0, 1.0)
    weekend = dt.dayofweek >= 5  # Sat=5, Sun=6
    return np.where(weekend, u_base * 0.6, u_base)


def _compute_outlet_temp(
    inlet_temp_C: np.ndarray,
    it_power_kw: np.ndarray,
) -> np.ndarray:
    """Outlet temp = inlet + IT_power_W / (ρ * airflow * cp)."""
    it_power_w = it_power_kw * 1000.0
    denominator = AIR_DENSITY_KG_M3 * AIRFLOW_M3_S * SPECIFIC_HEAT_AIR_J_KG_K
    delta_t = np.where(denominator > 0, it_power_w / denominator, 0.0)
    return inlet_temp_C + delta_t


def _compute_water_consumed(flow_lpm: np.ndarray) -> np.ndarray:
    """Water consumed = flow_lpm * 5_min * evaporation_rate_0.03."""
    return flow_lpm * INTERVAL_MINUTES * EVAPORATION_RATE


def generate_sensor_data(
    days: int = 90,
    seed: int | None = 42,
) -> pd.DataFrame:
    """
    Generate synthetic data centre sensor data.

    Args:
        days: Number of days to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with all sensor columns and anomaly labels.
    """
    if seed is not None:
        np.random.seed(seed)

    # Timestamps at 5-min intervals
    n_intervals = days * 24 * 60 // INTERVAL_MINUTES
    timestamps = pd.date_range(
        start="2024-01-01 00:00:00",
        periods=n_intervals,
        freq=f"{INTERVAL_MINUTES}min",
    )

    # 1. Server utilisation
    utilisation = _compute_utilisation(timestamps)

    # 2. Outside temp: seasonal + daily cycle + noise
    day_of_year = timestamps.dayofyear
    hour_frac = timestamps.hour + timestamps.minute / 60
    outside_temp = (
        20
        + 8 * np.sin(2 * np.pi * (day_of_year - 80) / 365)  # seasonal
        + 3 * np.sin(2 * np.pi * (hour_frac - 14) / 24)  # daily
        + np.random.normal(0, 1.0, n_intervals)
    )

    # 3. IT power
    it_power_kw = MAX_IT_POWER_KW * utilisation

    # 4. Inlet temp: cooled below outside, target ~22°C with variation
    inlet_temp = (
        22
        + 0.15 * (outside_temp - 25)
        + np.random.normal(0, 0.5, n_intervals)
    )
    inlet_temp = np.clip(inlet_temp, 18, 27)

    # 5. Outlet temp (physics)
    outlet_temp = _compute_outlet_temp(inlet_temp, it_power_kw)
    outlet_temp = np.clip(outlet_temp, inlet_temp, 50)

    # 6. Cooling power = IT_power / COP
    cooling_power_kw = it_power_kw / COP_EVAPORATIVE

    # 7. Total power & PUE
    total_power_kw = it_power_kw + cooling_power_kw
    pue = np.ones_like(it_power_kw)
    mask = it_power_kw > 0.1
    pue[mask] = total_power_kw[mask] / it_power_kw[mask]

    # 8. Water flow: base + scales with cooling load
    base_flow = 80.0
    flow_scale = 2.0
    water_flow_lpm = base_flow + flow_scale * cooling_power_kw + np.random.normal(0, 5, n_intervals)
    water_flow_lpm = np.clip(water_flow_lpm, 20, 300)

    # 9. Water consumed
    water_consumed_L = _compute_water_consumed(water_flow_lpm)

    # 10. WUE = water_consumed_L / (it_power_kw * interval_hours)
    interval_hours = INTERVAL_MINUTES / 60
    it_energy_kwh = it_power_kw * interval_hours
    wue = np.zeros_like(it_power_kw)
    mask = it_energy_kwh > 0.01
    wue[mask] = water_consumed_L[mask] / it_energy_kwh[mask]

    # 11. Humidity: 35-65% with daily variation
    humidity_pct = (
        50
        + 10 * np.sin(2 * np.pi * (hour_frac - 6) / 24)
        + np.random.normal(0, 3, n_intervals)
    )
    humidity_pct = np.clip(humidity_pct, 25, 75)

    # 12. Water pressure: nominal 3 bar
    water_pressure_bar = 3.0 + np.random.normal(0, 0.1, n_intervals)
    water_pressure_bar = np.clip(water_pressure_bar, 1.5, 5.0)

    # 13. Anomaly column (initially 0)
    anomaly = np.zeros(n_intervals, dtype=int)

    # Build DataFrame
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "server_utilisation": utilisation,
            "outside_temp_C": outside_temp,
            "server_inlet_temp_C": inlet_temp,
            "server_outlet_temp_C": outlet_temp,
            "it_power_kw": it_power_kw,
            "cooling_power_kw": cooling_power_kw,
            "total_power_kw": total_power_kw,
            "pue": pue,
            "water_flow_lpm": water_flow_lpm,
            "water_consumed_L": water_consumed_L,
            "wue": wue,
            "humidity_pct": humidity_pct,
            "water_pressure_bar": water_pressure_bar,
            "anomaly": anomaly,
        }
    )

    # 14. Inject 5 anomalies

    # 3 water leaks: pressure drop + flow spike
    n = len(df)
    leak_indices = np.random.choice(n, size=3, replace=False)
    for idx in leak_indices:
        # Anomaly window: 1 hour = 12 intervals
        start = max(0, idx - 6)
        end = min(n, idx + 6)
        df.loc[start:end, "anomaly"] = 1
        df.loc[start:end, "water_pressure_bar"] *= 0.4  # pressure drop
        df.loc[start:end, "water_flow_lpm"] *= 2.5  # flow spike (leak)

    # 2 thermal spikes: outlet temp spike (avoid overlap with leaks)
    exclude = set(leak_indices)
    candidates = [i for i in range(n) if i not in exclude]
    thermal_indices = np.random.choice(candidates, size=min(2, len(candidates)), replace=False)
    for idx in thermal_indices:
        start = max(0, idx - 4)
        end = min(n, idx + 4)
        df.loc[start:end, "anomaly"] = 1
        # Spike outlet temp by 8-15°C
        spike = np.random.uniform(8, 15)
        df.loc[start:end, "server_outlet_temp_C"] += spike

    return df


def print_summary(df: pd.DataFrame) -> None:
    """Print summary statistics for the generated data."""
    print("\n" + "=" * 60)
    print("SENSOR DATA SUMMARY")
    print("=" * 60)
    print(f"\nShape: {df.shape[0]:,} rows × {df.shape[1]} columns")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"\nAnomaly distribution: {df['anomaly'].value_counts().to_dict()}")

    numeric_cols = [
        "server_utilisation",
        "outside_temp_C",
        "server_inlet_temp_C",
        "server_outlet_temp_C",
        "it_power_kw",
        "cooling_power_kw",
        "total_power_kw",
        "pue",
        "water_flow_lpm",
        "water_consumed_L",
        "wue",
        "humidity_pct",
        "water_pressure_bar",
    ]
    print("\nNumeric column statistics:")
    print(df[numeric_cols].describe().round(4).to_string())

    print("\nCorrelation with anomaly:")
    for col in ["water_pressure_bar", "water_flow_lpm", "server_outlet_temp_C"]:
        corr = df[col].corr(df["anomaly"])
        print(f"  {col}: {corr:.4f}")


def main() -> None:
    """Generate data and save to CSV."""
    log_function_entry("data_generator.main")
    
    try:
        parser = argparse.ArgumentParser(description="Generate synthetic data centre sensor data")
        parser.add_argument("--days", type=int, default=90, help="Number of days to generate")
        parser.add_argument("--seed", type=int, default=42, help="Random seed")
        parser.add_argument(
            "--output",
            type=Path,
            default=Path("data/raw/sensor_data.csv"),
            help="Output CSV path",
        )
        args = parser.parse_args()

        logger.info(f"Generating {args.days} days of synthetic sensor data with seed {args.seed}")
        df = generate_sensor_data(days=args.days, seed=args.seed)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.output, index=False)
        logger.info(f"Saved {len(df)} records to {args.output}")
        print(f"Saved to {args.output}")

        print_summary(df)
        log_function_exit("data_generator.main", result=f"Generated {len(df)} records")
    except Exception as e:
        log_error("data_generator.main", e)
        raise


if __name__ == "__main__":
    main()
