"""
Generate synthetic data centre sensor data using the SAME physics as the
live digital twin (src/digital_twin.py) — see the module docstring below
for why this matters.

Output: data/raw/sensor_data.csv with timestamp, utilisation, temperatures,
power metrics, water metrics, cooling mode, water stress, and anomaly labels.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .digital_twin import CoolingMode, DigitalTwin
from .logging_config import log_error, log_function_entry, log_function_exit

logger = logging.getLogger(__name__)

# NOTE ON PHYSICS CONSTANTS: this module previously defined its own copies
# of COP, evaporation rate, airflow, air density, and specific heat --
# which had drifted from the values actually used by DigitalTwin (used by
# the live /api/state endpoint and the RL training environment). That
# meant training data was generated under different physics than the
# system it was training models for. Fixed by delegating every physics
# calculation to a real DigitalTwin instance below -- there is now exactly
# one physics implementation in this codebase.
MAX_IT_POWER_KW = 500.0
IDLE_POWER_FRACTION = 0.4
AIR_FLOW_M3_S = 8.0  # matches DigitalTwin's default -- previously this module used 50.0
INTERVAL_MINUTES = 5

REPO_ROOT = Path(__file__).resolve().parent.parent
CLEANED_WEATHER_PATH = REPO_ROOT / "data" / "cleaned" / "weather_open_meteo.csv"
CLEANED_WATER_STRESS_PATH = REPO_ROOT / "data" / "cleaned" / "water_stress_aqueduct.csv"


def _compute_utilisation(dt: pd.DatetimeIndex) -> np.ndarray:
    """
    Daily utilisation: 0.4 + 0.5*sin((hour-6)*pi/12) clipped to [0, 1].
    Weekend factor: 0.6x on Saturday/Sunday.

    NOTE: still synthetic. Wiring real Alibaba/Google cluster-trace
    utilisation in requires a Phase-2-style ingestion module for that
    source, which does not exist yet -- flagged here rather than silently
    left unmentioned.
    """
    hour = dt.hour + dt.minute / 60
    u_base = 0.4 + 0.5 * np.sin((hour - 6) * np.pi / 12)
    u_base = np.clip(u_base, 0.0, 1.0)
    weekend = dt.dayofweek >= 5  # Sat=5, Sun=6
    return np.where(weekend, u_base * 0.6, u_base)


def _load_real_weather(city: str, n_intervals: int, timestamps: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray] | None:
    """
    Load real outside_temp_C / humidity_pct for `city` from Phase 2's
    ingestion output, resampled to 5-min intervals and tiled/truncated to
    cover `n_intervals`. Returns None (triggering the synthetic fallback
    below) if the cleaned file doesn't exist yet or the city isn't in it --
    this keeps the generator runnable for anyone who hasn't run
    scripts/run_ingestion.py yet, rather than hard-failing.
    """
    if not CLEANED_WEATHER_PATH.exists():
        logger.warning(
            "%s not found -- run `python scripts/run_ingestion.py --only weather_open_meteo` "
            "to use real weather data. Falling back to synthetic outside_temp_C/humidity_pct.",
            CLEANED_WEATHER_PATH,
        )
        return None

    weather = pd.read_csv(CLEANED_WEATHER_PATH, parse_dates=["timestamp_utc"])
    city_data = weather[weather["city"].str.lower() == city.lower()].sort_values("timestamp_utc")
    if city_data.empty:
        available = sorted(weather["city"].unique())
        logger.warning(
            "City '%s' not found in %s (available: %s). Falling back to synthetic weather.",
            city, CLEANED_WEATHER_PATH, available,
        )
        return None

    city_data = city_data.set_index("timestamp_utc")[["outside_temp_C", "humidity_pct"]]
    # Real data is hourly for one calendar year; resample to 5-min via
    # linear interpolation, then tile/truncate to the requested length so
    # a 90-day (or longer) synthetic run can still draw from one real year.
    resampled = city_data.resample(f"{INTERVAL_MINUTES}min").interpolate("linear").dropna()
    if resampled.empty:
        logger.warning("Resampling produced no usable rows for city '%s'; falling back to synthetic.", city)
        return None

    reps = int(np.ceil(n_intervals / len(resampled)))
    tiled = pd.concat([resampled] * reps, ignore_index=True).iloc[:n_intervals]
    return tiled["outside_temp_C"].to_numpy(), tiled["humidity_pct"].to_numpy()


def _load_water_stress_baseline(country: str) -> float | None:
    """
    Load the real Aqueduct baseline water-stress score for `country`,
    min-max normalized to [0, 1] across the whole Aqueduct table (so the
    result is comparable regardless of Aqueduct's raw scoring scale).
    Returns None if the cleaned file or country isn't available.
    """
    if not CLEANED_WATER_STRESS_PATH.exists():
        logger.warning(
            "%s not found -- run `python scripts/run_ingestion.py --only water_stress_aqueduct` "
            "to use the real Aqueduct baseline. Falling back to a fully synthetic water_stress curve.",
            CLEANED_WATER_STRESS_PATH,
        )
        return None
    aqueduct = pd.read_csv(CLEANED_WATER_STRESS_PATH)
    # water_stress_aqueduct.py's normalize_aqueduct_dataframe() writes the
    # WRI Aqueduct 4.0 column names directly: "name_0" is the country name,
    # "bws_score" is the baseline water-stress score (0-5). This function
    # previously looked for "country"/"water_stress_score", which the
    # ingestion module never produces -- that mismatch is what raised
    # KeyError: 'country' here.
    required = {"name_0", "bws_score"}
    if not required.issubset(aqueduct.columns):
        logger.warning(
            "%s is missing expected columns %s (has %s); falling back to synthetic water_stress. "
            "Re-run `python scripts/run_ingestion.py --only water_stress_aqueduct` to regenerate it.",
            CLEANED_WATER_STRESS_PATH, sorted(required - set(aqueduct.columns)), list(aqueduct.columns),
        )
        return None

    country_rows = aqueduct[aqueduct["name_0"].str.lower() == country.lower()]
    if country_rows.empty:
        logger.warning("Country '%s' not found in %s; falling back to synthetic water_stress.", country, CLEANED_WATER_STRESS_PATH)
        return None

    scores = aqueduct["bws_score"].dropna()
    score_min, score_max = scores.min(), scores.max()
    if pd.isna(score_min) or score_max <= score_min:
        return 0.5  # degenerate case -- can't normalize a constant/all-NaN column
    raw = country_rows["bws_score"].dropna().mean()
    if pd.isna(raw):
        return None  # this country's own score is missing (WRI sentinel / no data)
    return float((raw - score_min) / (score_max - score_min))


def _compute_water_stress(
    n_intervals: int,
    timestamps: pd.DatetimeIndex,
    baseline: float | None,
) -> np.ndarray:
    """
    Build a time-varying water_stress signal in [0, 1].

    Aqueduct gives one static score per country, not a time series -- using
    it as a constant would give the RL agent's drought-mode arbitration
    (patent Claim 8) nothing to learn from, since the "trigger" would never
    change. So the real baseline (if available) sets the AVERAGE level, and
    a synthetic seasonal cycle plus a few injected multi-day drought
    episodes provide the variation needed to actually exercise and train
    the drought-responsive behaviour.
    """
    base = baseline if baseline is not None else 0.35  # documented synthetic default
    day_of_year = timestamps.dayofyear.to_numpy()
    seasonal = 0.15 * np.sin(2 * np.pi * (day_of_year - 172) / 365)  # drier mid-year, adjust per hemisphere/site
    noise = np.random.normal(0, 0.03, n_intervals)
    stress = np.clip(base + seasonal + noise, 0.0, 1.0)

    # Inject 2 multi-day drought episodes so the drought threshold (>0.7,
    # see DigitalTwin.select_cooling_mode) actually gets crossed during
    # training, not just approached.
    n_days = n_intervals * INTERVAL_MINUTES // (24 * 60)
    if n_days >= 14:  # only inject if there's enough data to make this meaningful
        episode_days = np.random.choice(range(3, n_days - 3), size=2, replace=False)
        intervals_per_day = 24 * 60 // INTERVAL_MINUTES
        for day in episode_days:
            start = day * intervals_per_day
            end = min(n_intervals, start + 3 * intervals_per_day)  # 3-day drought episode
            stress[start:end] = np.clip(stress[start:end] + np.random.uniform(0.4, 0.55), 0.0, 1.0)

    return stress


def generate_sensor_data(
    days: int = 90,
    seed: int | None = 42,
    city: str = "Delhi",
    country: str = "India",
) -> pd.DataFrame:
    """
    Generate synthetic data centre sensor data using DigitalTwin's own
    physics methods (see module docstring for why).

    Args:
        days: Number of days to generate.
        seed: Random seed for reproducibility.
        city: Open-Meteo city to draw real weather from, if
            data/cleaned/weather_open_meteo.csv exists (Phase 2 output).
        country: Aqueduct country to draw the real water-stress baseline
            from, if data/cleaned/water_stress_aqueduct.csv exists.

    Returns:
        DataFrame with all sensor columns, cooling_mode, water_stress, and
        anomaly labels.
    """
    if seed is not None:
        np.random.seed(seed)

    n_intervals = days * 24 * 60 // INTERVAL_MINUTES
    timestamps = pd.date_range(
        start="2024-01-01 00:00:00",
        periods=n_intervals,
        freq=f"{INTERVAL_MINUTES}min",
    )

    # 1. Server utilisation (still synthetic -- see _compute_utilisation docstring)
    utilisation = _compute_utilisation(timestamps)

    # 2. Outside temp / humidity: real if available, synthetic fallback otherwise
    real_weather = _load_real_weather(city, n_intervals, timestamps)
    if real_weather is not None:
        outside_temp, humidity_pct = real_weather
        logger.info("Using real Open-Meteo weather for city='%s'", city)
    else:
        day_of_year = timestamps.dayofyear
        hour_frac = timestamps.hour + timestamps.minute / 60
        outside_temp = (
            20
            + 8 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
            + 3 * np.sin(2 * np.pi * (hour_frac - 14) / 24)
            + np.random.normal(0, 1.0, n_intervals)
        )
        humidity_pct = (
            50
            + 10 * np.sin(2 * np.pi * (hour_frac - 6) / 24)
            + np.random.normal(0, 3, n_intervals)
        )
        humidity_pct = np.clip(humidity_pct, 25, 75)

    # 3. Water stress: real Aqueduct baseline + synthetic seasonal/drought overlay
    water_stress_baseline = _load_water_stress_baseline(country)
    if water_stress_baseline is not None:
        logger.info(
            "Using real Aqueduct water-stress baseline for country='%s': %.3f",
            country, water_stress_baseline,
        )
    water_stress = _compute_water_stress(n_intervals, timestamps, water_stress_baseline)

    # 4. Inlet temp: cooled below outside, target ~22C with variation
    inlet_temp = 22 + 0.15 * (outside_temp - 25) + np.random.normal(0, 0.5, n_intervals)
    inlet_temp = np.clip(inlet_temp, 18, 27)

    # 5-9. Physics: delegate to DigitalTwin's own methods, row by row, so
    # training data is generated by the exact same code path the live
    # system runs. 25,920 rows at ~5 method calls each is well under a
    # second in practice -- vectorizing this would mean re-deriving the
    # twin's logic a second time, which is the bug this phase is fixing.
    twin = DigitalTwin(
        max_it_power_kw=MAX_IT_POWER_KW,
        idle_power_fraction=IDLE_POWER_FRACTION,
        air_flow_m3_s=AIR_FLOW_M3_S,
    )

    it_power_kw = np.empty(n_intervals)
    outlet_temp = np.empty(n_intervals)
    cooling_power_kw = np.empty(n_intervals)
    cooling_mode = np.empty(n_intervals, dtype=object)
    water_flow_lpm = np.empty(n_intervals)
    water_consumed_L = np.empty(n_intervals)

    for i in range(n_intervals):
        u = float(np.clip(utilisation[i], 0.0, 1.0))
        it_power_kw[i] = twin.compute_it_power(u)
        outlet_temp[i] = twin.compute_outlet_temp(float(inlet_temp[i]), it_power_kw[i], airflow_m3_s=AIR_FLOW_M3_S)

        mode: CoolingMode = twin.select_cooling_mode(float(outside_temp[i]), float(water_stress[i]))
        cooling_mode[i] = mode.value
        cooling_power_kw[i] = twin.compute_cooling_power(it_power_kw[i], mode, float(outside_temp[i]))
        flow, consumed = twin.compute_water_consumption(cooling_power_kw[i], mode, float(outside_temp[i]))
        water_flow_lpm[i] = flow
        water_consumed_L[i] = consumed

    outlet_temp = np.clip(outlet_temp, inlet_temp, 50)

    # 10. Total power & PUE
    total_power_kw = it_power_kw + cooling_power_kw
    pue = np.ones_like(it_power_kw)
    mask = it_power_kw > 0.1
    pue[mask] = total_power_kw[mask] / it_power_kw[mask]

    # 11. WUE = water_consumed_L / (it_power_kw * interval_hours)
    interval_hours = INTERVAL_MINUTES / 60
    it_energy_kwh = it_power_kw * interval_hours
    wue = np.zeros_like(it_power_kw)
    mask = it_energy_kwh > 0.01
    wue[mask] = water_consumed_L[mask] / it_energy_kwh[mask]

    # 12. Water pressure: nominal 3 bar
    water_pressure_bar = 3.0 + np.random.normal(0, 0.1, n_intervals)
    water_pressure_bar = np.clip(water_pressure_bar, 1.5, 5.0)

    # 13. Anomaly column (initially 0) -- injection logic below is unchanged
    # from the previous version. Still only 5 events across the whole
    # dataset (flagged in the Phase 1 audit as thin); shaping this against
    # real NAB fault progressions is Phase 6 scope, not this phase.
    anomaly = np.zeros(n_intervals, dtype=int)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "server_utilisation": utilisation,
            "outside_temp_C": outside_temp,
            "server_inlet_temp_C": inlet_temp,
            "server_outlet_temp_C": outlet_temp,
            "it_power_kw": it_power_kw,
            "cooling_power_kw": cooling_power_kw,
            "cooling_mode": cooling_mode,
            "water_stress": water_stress,
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

    n = len(df)
    leak_indices = np.random.choice(n, size=3, replace=False)
    for idx in leak_indices:
        start = max(0, idx - 6)
        end = min(n, idx + 6)
        df.loc[start:end, "anomaly"] = 1
        df.loc[start:end, "water_pressure_bar"] *= 0.4
        df.loc[start:end, "water_flow_lpm"] *= 2.5

    exclude = set(leak_indices)
    candidates = [i for i in range(n) if i not in exclude]
    thermal_indices = np.random.choice(candidates, size=min(2, len(candidates)), replace=False)
    for idx in thermal_indices:
        start = max(0, idx - 4)
        end = min(n, idx + 4)
        df.loc[start:end, "anomaly"] = 1
        spike = np.random.uniform(8, 15)
        df.loc[start:end, "server_outlet_temp_C"] += spike

    return df


def print_summary(df: pd.DataFrame) -> None:
    """Print summary statistics for the generated data."""
    print("\n" + "=" * 60)
    print("SENSOR DATA SUMMARY")
    print("=" * 60)
    print(f"\nShape: {df.shape[0]:,} rows x {df.shape[1]} columns")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"\nAnomaly distribution: {df['anomaly'].value_counts().to_dict()}")
    print(f"\nCooling mode distribution:\n{df['cooling_mode'].value_counts().to_string()}")
    print(f"\nWater stress: min={df['water_stress'].min():.3f}, mean={df['water_stress'].mean():.3f}, max={df['water_stress'].max():.3f}")

    numeric_cols = [
        "server_utilisation", "outside_temp_C", "server_inlet_temp_C", "server_outlet_temp_C",
        "it_power_kw", "cooling_power_kw", "total_power_kw", "pue",
        "water_flow_lpm", "water_consumed_L", "wue", "humidity_pct", "water_pressure_bar", "water_stress",
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
        parser.add_argument("--city", type=str, default="Delhi", help="Open-Meteo city for real weather (Phase 2)")
        parser.add_argument("--country", type=str, default="India", help="Aqueduct country for real water-stress baseline (Phase 2)")
        parser.add_argument("--output", type=Path, default=Path("data/raw/sensor_data.csv"), help="Output CSV path")
        args = parser.parse_args()

        logger.info(f"Generating {args.days} days of synthetic sensor data with seed {args.seed}")
        df = generate_sensor_data(days=args.days, seed=args.seed, city=args.city, country=args.country)

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