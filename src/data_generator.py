"""
Generate synthetic data centre sensor data using the SAME physics as the
live digital twin (src/digital_twin.py) -- see the notes below for why this matters.

Two entry points:

* ``generate_scenario`` (T25): one scenario of the leakage-safe dataset v2 -- a window inside one city x month-block
  cell, one workload regime, one seed. Driven by configs/splits/*.json and configs/scenarios/*.json through
  scripts/make_datasets.py. Utilisation is synthetic (regimes ``low, diurnal, high, burst``); weather is the cleaned
  Open-Meteo year 2025.
* ``generate_sensor_data`` (legacy API, used by notebooks/train_all.py): a single 2024-01-01 series for one city.

T25 rules that apply to both:

* **Missing inputs raise.** data/cleaned/weather_open_meteo.csv and data/cleaned/water_stress_aqueduct.csv are
  required. ``allow_synthetic_weather`` / ``allow_synthetic_water_stress`` (CLI ``--allow-synthetic-weather`` /
  ``--allow-synthetic-water-stress``) are the only way to proceed without them, and every use is returned and recorded
  as ``synthetic_inputs`` (dataset manifest). Nothing is substituted silently.
* **No global RNG.** Every random draw comes from a ``numpy.random.Generator`` built from the scenario seed and a fixed
  stream id (``make_rng``); ``np.random.seed`` is never called, so results do not depend on call order elsewhere.
* **Anomaly injection writes an event table** ``(event_id, scenario_id, split, type, start, end, params)``; events
  never overlap, never touch the window edge margin, and cannot leave their scenario, hence never cross a split.

Output (legacy CLI): data/raw/sensor_data.csv with timestamp, utilisation, temperatures, power metrics, water
metrics, cooling mode, water stress, and anomaly labels.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_pipeline import (
    CLEANED_DIR,
    EVENT_COLUMNS,
    DatasetConfigError,
    MissingInputError,
    Scenario,
    canonical_json,
)
from .digital_twin import CoolingMode, DigitalTwin
from .logging_config import log_error, log_function_entry, log_function_exit

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "2"

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
CLEANED_WEATHER_PATH = CLEANED_DIR / "weather_open_meteo.csv"
CLEANED_WATER_STRESS_PATH = CLEANED_DIR / "water_stress_aqueduct.csv"

SYNTHETIC_WATER_STRESS_BASE = 0.35  # documented synthetic default, used only with allow_synthetic_water_stress

# Fixed RNG stream ids: one stream per purpose, so adding a draw to one purpose never shifts another.
STREAM_WINDOW, STREAM_WEATHER, STREAM_WORKLOAD, STREAM_WATER, STREAM_NOISE, STREAM_EVENTS = range(6)

LEGACY_INJECTION: dict[str, Any] = {
    "per_scenario": {
        "leak": {"count": 3, "half_width_intervals": 6, "pressure_factor": 0.4, "flow_factor": 2.5},
        "thermal": {"count": 2, "half_width_intervals": 4, "spike_C_range": [8.0, 15.0]},
    },
    "edge_margin_intervals": 0,
    "min_separation_intervals": 1,
}
LEGACY_WATER_STRESS: dict[str, Any] = {"drought_episodes": 2, "episode_days": 3, "min_days_for_episodes": 14}


def make_rng(seed: int | None, stream: int) -> np.random.Generator:
    """The generator for (``seed``, ``stream``). ``seed=None`` means fresh OS entropy (non-reproducible)."""
    if seed is None:
        return np.random.default_rng()
    return np.random.default_rng(np.random.SeedSequence([int(seed), int(stream)]))


# ----------------------------------------------------------------------------- workload (synthetic)
def _hour_of_day(timestamps: pd.DatetimeIndex) -> np.ndarray:
    """Fractional hour of day as a plain float ndarray (not a pandas Index)."""
    return np.asarray(timestamps.hour, dtype=float) + np.asarray(timestamps.minute, dtype=float) / 60


def _diurnal_base(timestamps: pd.DatetimeIndex) -> np.ndarray:
    """0.4 + 0.5*sin((hour-6)*pi/12) clipped to [0, 1]; 0.6x on Saturday/Sunday."""
    hour = _hour_of_day(timestamps)
    u_base = np.clip(0.4 + 0.5 * np.sin((hour - 6) * np.pi / 12), 0.0, 1.0)
    return np.where(np.asarray(timestamps.dayofweek) >= 5, u_base * 0.6, u_base)


def compute_utilisation(
    timestamps: pd.DatetimeIndex, regime: str = "diurnal", rng: np.random.Generator | None = None
) -> np.ndarray:
    """Synthetic server utilisation in [0, 1] for one workload regime (``low, diurnal, high, burst``).

    NOT real workload: wiring real Alibaba/Google cluster-trace utilisation in needs an ingestion module for that
    source, which does not exist. ``diurnal`` with no noise is the original curve (legacy behaviour)."""
    n = len(timestamps)
    hour = _hour_of_day(timestamps)
    if regime == "diurnal":
        return _diurnal_base(timestamps)
    if rng is None:
        raise ValueError(f"regime {regime!r} needs an rng")
    if regime == "low":
        u = 0.15 + 0.05 * np.sin((hour - 6) * np.pi / 12) + rng.normal(0, 0.02, n)
    elif regime == "high":
        u = 0.75 + 0.15 * np.sin((hour - 6) * np.pi / 12) + rng.normal(0, 0.03, n)
    elif regime == "burst":
        u = _diurnal_base(timestamps) + rng.normal(0, 0.02, n)
        per_day = 24 * 60 // INTERVAL_MINUTES
        n_days = max(1, n // per_day)
        for day in range(n_days):
            for _ in range(int(rng.integers(2, 5))):  # 2-4 bursts per day, 1-3 hours long
                start = day * per_day + int(rng.integers(0, per_day))
                length = int(rng.integers(12, 37))
                u[start : start + length] = rng.uniform(0.9, 1.0)
    else:
        raise ValueError(f"unknown workload regime {regime!r}")
    return np.clip(u, 0.0, 1.0)


# ----------------------------------------------------------------------------- cleaned inputs (strict)
def load_cleaned_weather(path: Path = CLEANED_WEATHER_PATH) -> pd.DataFrame:
    """The cleaned Open-Meteo table (``timestamp_utc, city, outside_temp_C, humidity_pct``). Raises if missing."""
    if not Path(path).is_file():
        raise MissingInputError(
            f"required cleaned input is missing: {path}. Supply realData/open_meteo and run "
            "`python scripts/run_ingestion.py --only weather_open_meteo`, or pass --allow-synthetic-weather "
            "(recorded as synthetic_inputs)."
        )
    weather = pd.read_csv(path, parse_dates=["timestamp_utc"])
    if weather["timestamp_utc"].dt.tz is not None:
        weather["timestamp_utc"] = weather["timestamp_utc"].dt.tz_convert("UTC").dt.tz_localize(None)
    return weather


def city_weather_5min(weather: pd.DataFrame, city: str) -> pd.DataFrame | None:
    """Hourly -> 5-minute (linear interpolation) for one city, or None if the city is absent."""
    rows = weather[weather["city"].str.lower() == city.lower()].sort_values("timestamp_utc")
    if rows.empty:
        return None
    series = rows.set_index("timestamp_utc")[["outside_temp_C", "humidity_pct"]]
    series = series[~series.index.duplicated(keep="first")]
    return series.resample(f"{INTERVAL_MINUTES}min").interpolate("linear").dropna()


def load_water_stress_baseline(country: str, path: Path = CLEANED_WATER_STRESS_PATH) -> float:
    """The real Aqueduct baseline water-stress score for ``country``, min-max normalised to [0, 1] across the table.
    Raises MissingInputError if the file, its columns, or the country are missing."""
    if not Path(path).is_file():
        raise MissingInputError(
            f"required cleaned input is missing: {path}. Run `python scripts/run_ingestion.py --only "
            "water_stress_aqueduct`, or pass --allow-synthetic-water-stress (recorded as synthetic_inputs)."
        )
    aqueduct = pd.read_csv(path)
    # water_stress_aqueduct.py's normalize_aqueduct_dataframe() writes the WRI Aqueduct 4.0 column names directly:
    # "name_0" is the country name, "bws_score" is the baseline water-stress score (0-5).
    required = {"name_0", "bws_score"}
    if not required.issubset(aqueduct.columns):
        raise MissingInputError(f"{path} lacks columns {sorted(required - set(aqueduct.columns))}")
    country_rows = aqueduct[aqueduct["name_0"].str.lower() == country.lower()]
    if country_rows.empty:
        raise MissingInputError(f"country {country!r} not found in {path}")
    scores = aqueduct["bws_score"].dropna()
    score_min, score_max = scores.min(), scores.max()
    if pd.isna(score_min) or score_max <= score_min:
        return 0.5  # degenerate case -- can't normalise a constant/all-NaN column
    raw = country_rows["bws_score"].dropna().mean()
    if pd.isna(raw):
        raise MissingInputError(f"country {country!r} has no baseline score in {path}")
    return float((raw - score_min) / (score_max - score_min))


def _synthetic_weather(timestamps: pd.DatetimeIndex, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    n = len(timestamps)
    day_of_year = np.asarray(timestamps.dayofyear, dtype=float)
    hour_frac = _hour_of_day(timestamps)
    outside_temp = (
        20
        + 8 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
        + 3 * np.sin(2 * np.pi * (hour_frac - 14) / 24)
        + rng.normal(0, 1.0, n)
    )
    humidity_pct = np.clip(50 + 10 * np.sin(2 * np.pi * (hour_frac - 6) / 24) + rng.normal(0, 3, n), 25, 75)
    return np.asarray(outside_temp), np.asarray(humidity_pct)


def _compute_water_stress(
    timestamps: pd.DatetimeIndex, baseline: float | None, rng: np.random.Generator, cfg: Mapping[str, Any]
) -> np.ndarray:
    """Time-varying water_stress in [0, 1]. Aqueduct gives one static score per country, so the real baseline (if any)
    sets the AVERAGE level and a synthetic seasonal cycle plus multi-day drought episodes provide the variation the
    drought-responsive behaviour needs."""
    n = len(timestamps)
    base = baseline if baseline is not None else SYNTHETIC_WATER_STRESS_BASE
    seasonal = 0.15 * np.sin(2 * np.pi * (timestamps.dayofyear.to_numpy() - 172) / 365)
    stress = np.clip(base + seasonal + rng.normal(0, 0.03, n), 0.0, 1.0)

    n_days = n * INTERVAL_MINUTES // (24 * 60)
    episodes = int(cfg["drought_episodes"])
    length_days = int(cfg["episode_days"])
    if n_days >= int(cfg["min_days_for_episodes"]) and episodes > 0:
        candidates = np.arange(3, n_days - 3)
        episode_days = rng.choice(candidates, size=min(episodes, len(candidates)), replace=False)
        per_day = 24 * 60 // INTERVAL_MINUTES
        for day in episode_days:
            start = int(day) * per_day
            end = min(n, start + length_days * per_day)
            stress[start:end] = np.clip(stress[start:end] + rng.uniform(0.4, 0.55), 0.0, 1.0)
    return stress


# ----------------------------------------------------------------------------- physics
def _simulate(
    timestamps: pd.DatetimeIndex,
    utilisation: np.ndarray,
    outside_temp: np.ndarray,
    humidity_pct: np.ndarray,
    water_stress: np.ndarray,
    rng: np.random.Generator,
    facility: Mapping[str, Any],
) -> tuple[pd.DataFrame, str]:
    """Run DigitalTwin's own methods row by row (one physics implementation). Returns (frame, physics_version)."""
    n = len(timestamps)
    inlet_temp = np.clip(22 + 0.15 * (outside_temp - 25) + rng.normal(0, 0.5, n), 18, 27)

    twin = DigitalTwin(
        max_it_power_kw=float(facility.get("max_it_power_kw", MAX_IT_POWER_KW)),
        idle_power_fraction=float(facility.get("idle_power_fraction", IDLE_POWER_FRACTION)),
        air_flow_m3_s=float(facility.get("air_flow_m3_s", AIR_FLOW_M3_S)),
        physics_version=facility.get("physics_version"),
    )
    it_power_kw = np.empty(n)
    outlet_temp = np.empty(n)
    cooling_power_kw = np.empty(n)
    cooling_mode = np.empty(n, dtype=object)
    water_flow_lpm = np.empty(n)
    water_consumed_L = np.empty(n)

    for i in range(n):
        u = float(np.clip(utilisation[i], 0.0, 1.0))
        it_power_kw[i] = twin.compute_it_power(u)
        outlet_temp[i] = twin.compute_outlet_temp(
            float(inlet_temp[i]), it_power_kw[i], airflow_m3_s=twin.effective_air_flow_m3_s(it_power_kw[i])
        )
        mode: CoolingMode = twin.select_cooling_mode(float(outside_temp[i]), float(water_stress[i]))
        cooling_mode[i] = mode.value
        cooling_power_kw[i] = twin.compute_cooling_power(it_power_kw[i], mode, float(outside_temp[i]))
        flow, consumed = twin.compute_water_consumption(cooling_power_kw[i], mode, float(outside_temp[i]))
        water_flow_lpm[i] = flow
        water_consumed_L[i] = consumed

    outlet_temp = np.clip(outlet_temp, inlet_temp, 50)
    total_power_kw = it_power_kw + cooling_power_kw
    pue = np.ones_like(it_power_kw)
    mask = it_power_kw > 0.1
    pue[mask] = total_power_kw[mask] / it_power_kw[mask]

    it_energy_kwh = it_power_kw * (INTERVAL_MINUTES / 60)
    wue = np.zeros_like(it_power_kw)
    mask = it_energy_kwh > 0.01
    wue[mask] = water_consumed_L[mask] / it_energy_kwh[mask]

    water_pressure_bar = np.clip(3.0 + rng.normal(0, 0.1, n), 1.5, 5.0)  # nominal 3 bar

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
            "anomaly": np.zeros(n, dtype=int),
            "event_id": "",
        }
    )
    return df, twin.physics_version


# ----------------------------------------------------------------------------- anomaly events
def inject_anomalies(
    df: pd.DataFrame,
    rng: np.random.Generator,
    injection: Mapping[str, Any],
    *,
    scenario_id: str,
    split: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inject the configured events into ``df`` (in place) and return ``(df, event_table)``.

    Events are half-open ``[start_idx, end_idx)`` row ranges, never overlap (``min_separation_intervals`` apart)
    and stay ``edge_margin_intervals`` away from both ends of the scenario, so each lies entirely inside it."""
    n = len(df)
    margin = int(injection["edge_margin_intervals"])
    separation = int(injection["min_separation_intervals"])
    taken: list[tuple[int, int]] = []
    plan: list[tuple[str, Mapping[str, Any]]] = []
    for etype, spec in injection["per_scenario"].items():
        plan.extend((etype, spec) for _ in range(int(spec["count"])))
    events: list[dict[str, Any]] = []
    ts = pd.DatetimeIndex(df["timestamp"])

    for k, (etype, spec) in enumerate(plan):
        half = int(spec["half_width_intervals"])
        lo, hi = margin + half, n - margin - half - 1
        if hi < lo:
            raise DatasetConfigError(f"scenario {scenario_id}: {n} rows are too few for a {etype} event")
        for _ in range(1000):
            center = int(rng.integers(lo, hi + 1))
            start, end = center - half, center + half + 1
            if all(end + separation <= a or start >= b + separation for a, b in taken):
                break
        else:
            raise DatasetConfigError(f"scenario {scenario_id}: cannot place {len(plan)} events without overlap")
        taken.append((start, end))
        event_id = f"{scenario_id}-E{k:02d}"
        rows = slice(start, end)
        if etype == "leak":
            df.iloc[rows, df.columns.get_loc("water_pressure_bar")] *= float(spec["pressure_factor"])
            df.iloc[rows, df.columns.get_loc("water_flow_lpm")] *= float(spec["flow_factor"])
            params: dict[str, Any] = {
                "center_idx": center,
                "pressure_factor": float(spec["pressure_factor"]),
                "flow_factor": float(spec["flow_factor"]),
            }
        elif etype == "thermal":
            lo_c, hi_c = spec["spike_C_range"]
            spike = float(rng.uniform(lo_c, hi_c))
            df.iloc[rows, df.columns.get_loc("server_outlet_temp_C")] += spike
            params = {"center_idx": center, "spike_C": spike}
        else:
            raise DatasetConfigError(f"unknown anomaly type {etype!r}")
        df.iloc[rows, df.columns.get_loc("anomaly")] = 1
        df.iloc[rows, df.columns.get_loc("event_id")] = event_id
        end_ts = ts[start] + (end - start) * pd.Timedelta(minutes=INTERVAL_MINUTES)
        events.append(
            {
                "event_id": event_id,
                "scenario_id": scenario_id,
                "split": split,
                "type": etype,
                "start": ts[start].isoformat(),
                "end": end_ts.isoformat(),
                "start_idx": start,
                "end_idx": end,
                "params": canonical_json(params),
            }
        )
    return df, pd.DataFrame(events, columns=list(EVENT_COLUMNS))


# ----------------------------------------------------------------------------- scenario generator (T25)
def _window_timestamps(
    scenario: Scenario, split_cfg: Mapping[str, Any], rng: np.random.Generator, interval_minutes: int
) -> pd.DatetimeIndex:
    """A contiguous ``days`` window chosen (by the seed) entirely inside the scenario's month-block."""
    months = split_cfg["month_blocks"][scenario.month_block]
    year = int(split_cfg["year"])
    first = date(year, min(months), 1)
    last_exclusive = date(year + 1, 1, 1) if max(months) == 12 else date(year, max(months) + 1, 1)
    # The hourly weather ends at HH:00 of the last day, so a 5-minute window may not end on that day: leave it out.
    span_days = (last_exclusive - first).days - 1
    if scenario.days > span_days:
        raise DatasetConfigError(f"{scenario.days}-day scenario does not fit month-block {scenario.month_block}")
    offset = int(rng.integers(0, span_days - scenario.days + 1))
    start = first + timedelta(days=offset)
    n = scenario.days * 24 * 60 // interval_minutes
    return pd.date_range(pd.Timestamp(start), periods=n, freq=f"{interval_minutes}min")


def generate_scenario(
    scenario: Scenario,
    split_cfg: Mapping[str, Any],
    scenario_cfg: Mapping[str, Any],
    *,
    weather: pd.DataFrame | None,
    water_stress_baseline: float | None,
    allow_synthetic_weather: bool = False,
    allow_synthetic_water_stress: bool = False,
    _city_cache: dict[str, pd.DataFrame | None] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """One scenario -> ``(rows, event_table, synthetic_inputs)``.

    ``weather`` is the cleaned table (``load_cleaned_weather``); ``None`` is allowed only with
    ``allow_synthetic_weather``. ``water_stress_baseline`` likewise (``load_water_stress_baseline``). Every substitution
    is returned in ``synthetic_inputs`` as ``"weather:<city>"`` / ``"water_stress:<country>"``."""
    interval = int(scenario_cfg["interval_minutes"])
    synthetic: list[str] = []
    ts = _window_timestamps(scenario, split_cfg, make_rng(scenario.seed, STREAM_WINDOW), interval)

    # outside temperature / humidity: cleaned real weather, or (explicitly allowed) synthetic
    outside_temp = humidity = None
    if weather is not None:
        cache = _city_cache if _city_cache is not None else {}
        if scenario.city not in cache:
            cache[scenario.city] = city_weather_5min(weather, scenario.city)
        series = cache[scenario.city]
        if series is not None:
            window = series.reindex(ts)
            if window.isna().any().any():
                raise MissingInputError(
                    f"cleaned weather for {scenario.city} does not cover {ts[0]} .. {ts[-1]} "
                    f"({int(window.isna().any(axis=1).sum())} missing rows)"
                )
            outside_temp, humidity = window["outside_temp_C"].to_numpy(), window["humidity_pct"].to_numpy()
    if outside_temp is None:
        if not allow_synthetic_weather:
            raise MissingInputError(
                f"no cleaned weather for city {scenario.city!r} and --allow-synthetic-weather was not given"
            )
        outside_temp, humidity = _synthetic_weather(ts, make_rng(scenario.seed, STREAM_WEATHER))
        synthetic.append(f"weather:{scenario.city}")

    if water_stress_baseline is None:
        if not allow_synthetic_water_stress:
            raise MissingInputError("no Aqueduct baseline and --allow-synthetic-water-stress was not given")
        synthetic.append(f"water_stress:{split_cfg.get('country', 'unknown')}")

    utilisation = compute_utilisation(ts, scenario.regime, make_rng(scenario.seed, STREAM_WORKLOAD))
    water_stress = _compute_water_stress(
        ts, water_stress_baseline, make_rng(scenario.seed, STREAM_WATER), scenario_cfg["water_stress"]
    )
    df, physics_version = _simulate(
        ts,
        utilisation,
        outside_temp,
        humidity,
        water_stress,
        make_rng(scenario.seed, STREAM_NOISE),
        scenario_cfg["facility"],
    )
    df, events = inject_anomalies(
        df,
        make_rng(scenario.seed, STREAM_EVENTS),
        scenario_cfg["injection"],
        scenario_id=scenario.scenario_id,
        split=scenario.split,
    )
    df.insert(0, "scenario_id", scenario.scenario_id)
    df.insert(1, "split", scenario.split)
    df.insert(2, "city", scenario.city)
    df.insert(3, "month_block", scenario.month_block)
    df.insert(4, "regime", scenario.regime)
    df.attrs["physics_version"] = physics_version
    return df, events, synthetic


# ----------------------------------------------------------------------------- legacy single-series API
def generate_sensor_data(
    days: int = 90,
    seed: int | None = 42,
    city: str = "Delhi",
    country: str = "India",
    *,
    allow_synthetic_weather: bool = False,
    allow_synthetic_water_stress: bool = False,
    return_events: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """One synthetic series starting 2024-01-01, using DigitalTwin's own physics.

    Raises ``MissingInputError`` if the cleaned weather (for ``city``) or the Aqueduct baseline (for ``country``) is
    missing, unless the matching ``allow_synthetic_*`` flag is set; substitutions are listed in
    ``df.attrs["synthetic_inputs"]``. Randomness comes from Generators seeded by ``seed``; the global NumPy RNG is not
    touched. With ``return_events=True`` the injected-event table is returned as well.
    """
    n_intervals = days * 24 * 60 // INTERVAL_MINUTES
    timestamps = pd.date_range(start="2024-01-01 00:00:00", periods=n_intervals, freq=f"{INTERVAL_MINUTES}min")
    synthetic: list[str] = []

    outside_temp = humidity_pct = None
    if CLEANED_WEATHER_PATH.is_file() or not allow_synthetic_weather:
        series = city_weather_5min(load_cleaned_weather(), city)  # raises MissingInputError if the file is missing
        if series is not None and not series.empty:
            # Real data is hourly for one calendar year: tile/truncate so a long run can still draw from one real year.
            reps = int(np.ceil(n_intervals / len(series)))
            tiled = pd.concat([series] * reps, ignore_index=True).iloc[:n_intervals]
            outside_temp, humidity_pct = tiled["outside_temp_C"].to_numpy(), tiled["humidity_pct"].to_numpy()
    if outside_temp is None:
        if not allow_synthetic_weather:
            raise MissingInputError(f"no cleaned weather for city {city!r}; pass allow_synthetic_weather=True")
        outside_temp, humidity_pct = _synthetic_weather(timestamps, make_rng(seed, STREAM_WEATHER))
        synthetic.append(f"weather:{city}")

    try:
        baseline: float | None = load_water_stress_baseline(country)
    except MissingInputError:
        if not allow_synthetic_water_stress:
            raise
        baseline = None
        synthetic.append(f"water_stress:{country}")

    utilisation = compute_utilisation(timestamps, "diurnal")  # legacy curve, still synthetic
    water_stress = _compute_water_stress(timestamps, baseline, make_rng(seed, STREAM_WATER), LEGACY_WATER_STRESS)
    facility = {
        "max_it_power_kw": MAX_IT_POWER_KW,
        "idle_power_fraction": IDLE_POWER_FRACTION,
        "air_flow_m3_s": AIR_FLOW_M3_S,
    }
    df, physics_version = _simulate(
        timestamps,
        utilisation,
        outside_temp,
        humidity_pct,
        water_stress,
        make_rng(seed, STREAM_NOISE),
        facility,
    )
    df, events = inject_anomalies(
        df, make_rng(seed, STREAM_EVENTS), LEGACY_INJECTION, scenario_id=f"legacy-{seed}", split="legacy"
    )
    df = df.drop(columns=["event_id"])
    df.attrs["synthetic_inputs"] = synthetic
    df.attrs["physics_version"] = physics_version
    return (df, events) if return_events else df


def print_summary(df: pd.DataFrame) -> None:
    """Print summary statistics for the generated data."""
    print("\n" + "=" * 60)
    print("SENSOR DATA SUMMARY")
    print("=" * 60)
    print(f"\nShape: {df.shape[0]:,} rows x {df.shape[1]} columns")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"\nAnomaly distribution: {df['anomaly'].value_counts().to_dict()}")
    print(f"\nCooling mode distribution:\n{df['cooling_mode'].value_counts().to_string()}")
    print(
        f"\nWater stress: min={df['water_stress'].min():.3f}, mean={df['water_stress'].mean():.3f}, "
        f"max={df['water_stress'].max():.3f}"
    )

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
        "water_stress",
    ]
    print("\nNumeric column statistics:")
    print(df[numeric_cols].describe().round(4).to_string())

    print("\nCorrelation with anomaly:")
    for col in ["water_pressure_bar", "water_flow_lpm", "server_outlet_temp_C"]:
        corr = df[col].corr(df["anomaly"])
        print(f"  {col}: {corr:.4f}")


def main() -> None:
    """Generate the legacy single series and save it to CSV."""
    log_function_entry("data_generator.main")

    try:
        parser = argparse.ArgumentParser(description="Generate synthetic data centre sensor data")
        parser.add_argument("--days", type=int, default=90, help="Number of days to generate")
        parser.add_argument("--seed", type=int, default=42, help="Random seed")
        parser.add_argument("--city", type=str, default="Delhi", help="Open-Meteo city for real weather")
        parser.add_argument("--country", type=str, default="India", help="Aqueduct country (water-stress baseline)")
        parser.add_argument("--output", type=Path, default=Path("data/raw/sensor_data.csv"), help="Output CSV path")
        parser.add_argument(
            "--allow-synthetic-weather",
            action="store_true",
            help="Proceed with synthetic weather if the cleaned Open-Meteo file/city is missing (otherwise: error)",
        )
        parser.add_argument(
            "--allow-synthetic-water-stress",
            action="store_true",
            help="Proceed with the synthetic water-stress baseline if the Aqueduct file/country is missing",
        )
        args = parser.parse_args()

        logger.info(f"Generating {args.days} days of synthetic sensor data with seed {args.seed}")
        df = generate_sensor_data(
            days=args.days,
            seed=args.seed,
            city=args.city,
            country=args.country,
            allow_synthetic_weather=args.allow_synthetic_weather,
            allow_synthetic_water_stress=args.allow_synthetic_water_stress,
        )
        if df.attrs.get("synthetic_inputs"):
            logger.warning("SYNTHETIC INPUTS USED: %s", df.attrs["synthetic_inputs"])

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
