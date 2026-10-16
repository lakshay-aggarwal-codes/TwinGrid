"""Task 25: tariff arithmetic. PURE: no I/O, no clock, no twin. Every number is a product or sum of its inputs.

The model is deliberately small and ILLUSTRATIVE: two energy rates (peak / off-peak) chosen by hour of day, and one
demand charge on the highest power draw, prorated from a billing period to the 24 h that was simulated. It is not a
quote, not a utility's published tariff, and not calibrated to any site. The currency is a label only: rates are
entered in that currency and nothing is converted.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

ILLUSTRATIVE_LABEL = "illustrative tariff, not a quote"
HOURS_PER_DAY = 24
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class TariffError(ValueError):
    """An input the model refuses (bad rate, hour, currency, profile length)."""


@dataclass(frozen=True)
class Tariff:
    """Rates are per kWh and per kW of peak demand per billing period, all in ``currency``.

    ``peak_start_hour`` / ``peak_end_hour``: hour of day of the simulated clock, start inclusive, end exclusive. If
    start > end the window wraps midnight (22 -> 6); start == end means there is no peak window (all off-peak).
    """

    currency: str = "USD"
    off_peak_rate: float = 0.08
    peak_rate: float = 0.18
    peak_start_hour: int = 16
    peak_end_hour: int = 21
    demand_charge_per_kw: float = 12.0
    billing_days: int = 30

    def validate(self) -> Tariff:
        if not _CURRENCY.match(self.currency):
            raise TariffError("currency must be a three-letter code such as USD")
        for name in ("off_peak_rate", "peak_rate", "demand_charge_per_kw"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int | float) or v != v or v < 0 or v == float("inf"):
                raise TariffError(f"{name} must be a finite number >= 0")
        for name in ("peak_start_hour", "peak_end_hour"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= HOURS_PER_DAY:
                raise TariffError(f"{name} must be a whole hour from 0 to 24")
        if (
            isinstance(self.billing_days, bool)
            or not isinstance(self.billing_days, int)
            or not 1 <= self.billing_days <= 366
        ):
            raise TariffError("billing_days must be a whole number from 1 to 366")
        return self

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


DEFAULT_TARIFF = Tariff()


def is_peak_hour(t: Tariff, hour: int) -> bool:
    """True when ``hour`` (0-23) falls in the peak window."""
    if not 0 <= hour < HOURS_PER_DAY:
        raise TariffError("hour must be 0-23")
    s, e = t.peak_start_hour, t.peak_end_hour
    if s == e:
        return False
    if s < e:
        return s <= hour < e
    return hour >= s or hour < e


def rate_for_hour(t: Tariff, hour: int) -> float:
    return t.peak_rate if is_peak_hour(t, hour) else t.off_peak_rate


@dataclass(frozen=True)
class CostBreakdown:
    energy_kwh: float
    peak_kwh: float
    off_peak_kwh: float
    energy_cost: float
    peak_kw: float
    demand_cost: float
    total_cost: float


def flat_hourly_profile(total_kwh: float) -> list[float]:
    """The simulated 24 h run holds its inputs constant, so its energy is spread evenly over the 24 hours."""
    if total_kwh < 0 or total_kwh != total_kwh:
        raise TariffError("energy must be >= 0")
    return [total_kwh / HOURS_PER_DAY] * HOURS_PER_DAY


def demand_cost(t: Tariff, peak_kw: float) -> float:
    """Demand charge for one day: ``rate * peak_kw`` is per billing period, so one day carries ``1 / billing_days`` of it."""
    if peak_kw < 0 or peak_kw != peak_kw:
        raise TariffError("peak_kw must be >= 0")
    return t.demand_charge_per_kw * peak_kw / t.billing_days


def daily_cost(t: Tariff, hourly_kwh: Sequence[float], peak_kw: float | None = None) -> CostBreakdown:
    """Cost of one day. ``hourly_kwh[h]`` is the energy used in hour-of-day ``h`` (exactly 24 values, each >= 0).

    ``peak_kw`` defaults to the largest hourly energy (kWh in one hour equals mean kW over it); pass a measured or
    simulated peak when a finer one exists.
    """
    t.validate()
    if len(hourly_kwh) != HOURS_PER_DAY:
        raise TariffError("hourly_kwh must have exactly 24 values")
    if any(v < 0 or v != v for v in hourly_kwh):
        raise TariffError("hourly energy must be >= 0")
    peak_kwh = sum(v for h, v in enumerate(hourly_kwh) if is_peak_hour(t, h))
    total = float(sum(hourly_kwh))
    off_peak_kwh = total - peak_kwh
    energy_cost = peak_kwh * t.peak_rate + off_peak_kwh * t.off_peak_rate
    kw = max(hourly_kwh) if peak_kw is None else peak_kw
    dc = demand_cost(t, kw)
    return CostBreakdown(total, peak_kwh, off_peak_kwh, energy_cost, kw, dc, energy_cost + dc)


@dataclass(frozen=True)
class Savings:
    """``baseline - scenario``: positive means the scenario costs less. Percent is None when the baseline cost is 0."""

    energy_cost: float
    demand_cost: float
    total_cost: float
    total_pct: float | None


def savings(baseline: CostBreakdown, scenario: CostBreakdown) -> Savings:
    pct = (
        None if baseline.total_cost == 0 else (baseline.total_cost - scenario.total_cost) / baseline.total_cost * 100.0
    )
    return Savings(
        baseline.energy_cost - scenario.energy_cost,
        baseline.demand_cost - scenario.demand_cost,
        baseline.total_cost - scenario.total_cost,
        pct,
    )
