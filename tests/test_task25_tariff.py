"""Task 25: golden-number tests for the tariff arithmetic and the summary assembly. No FastAPI client, DB or twin run."""

from __future__ import annotations

import pytest

from api.plugins import economics as E
from api.services import scenario_registry as SR
from src.economics import tariff as T

D = T.DEFAULT_TARIFF  # USD, off-peak 0.08, peak 0.18, peak 16:00-21:00, demand 12 per kW-month, 30-day period


def test_default_is_labelled_illustrative_and_validates():
    assert T.ILLUSTRATIVE_LABEL == "illustrative tariff, not a quote"
    assert D.validate() is D


@pytest.mark.parametrize(
    "hour,peak",
    [(0, False), (15, False), (16, True), (20, True), (21, False), (23, False)],
)
def test_peak_window_is_start_inclusive_end_exclusive(hour, peak):
    assert T.is_peak_hour(D, hour) is peak
    assert T.rate_for_hour(D, hour) == (0.18 if peak else 0.08)


def test_window_that_wraps_midnight_and_empty_window():
    night = T.Tariff(peak_start_hour=22, peak_end_hour=6)
    assert [h for h in range(24) if T.is_peak_hour(night, h)] == [0, 1, 2, 3, 4, 5, 22, 23]
    none = T.Tariff(peak_start_hour=9, peak_end_hour=9)
    assert not any(T.is_peak_hour(none, h) for h in range(24))


def test_golden_flat_100_kwh_per_hour():
    b = T.daily_cost(D, [100.0] * 24)
    assert b.energy_kwh == 2400.0
    assert b.peak_kwh == 500.0 and b.off_peak_kwh == 1900.0
    assert b.energy_cost == pytest.approx(242.0)  # 500*0.18 + 1900*0.08
    assert b.peak_kw == 100.0
    assert b.demand_cost == pytest.approx(40.0)  # 12 * 100 / 30
    assert b.total_cost == pytest.approx(282.0)


def test_golden_uneven_profile_uses_the_largest_hour_as_demand():
    hourly = [10.0] * 24
    hourly[18] = 60.0  # one peak-window hour
    b = T.daily_cost(D, hourly)
    assert b.energy_kwh == pytest.approx(290.0)
    assert b.peak_kwh == pytest.approx(10 * 4 + 60)  # hours 16,17,19,20 + 18
    assert b.energy_cost == pytest.approx(100 * 0.18 + 190 * 0.08)  # 18 + 15.2
    assert b.peak_kw == 60.0
    assert b.demand_cost == pytest.approx(24.0)  # 12 * 60 / 30
    assert b.total_cost == pytest.approx(57.2)


def test_explicit_peak_kw_overrides_the_default():
    assert T.daily_cost(D, [1.0] * 24, peak_kw=300.0).demand_cost == pytest.approx(120.0)


def test_zero_rates_and_zero_energy():
    free = T.Tariff(off_peak_rate=0, peak_rate=0, demand_charge_per_kw=0)
    assert T.daily_cost(free, [50.0] * 24).total_cost == 0.0
    assert T.daily_cost(D, [0.0] * 24).total_cost == 0.0


def test_currency_is_a_label_only():
    eur = T.Tariff(currency="EUR")
    assert T.daily_cost(eur, [100.0] * 24).total_cost == T.daily_cost(D, [100.0] * 24).total_cost


def test_flat_profile_spreads_evenly():
    p = T.flat_hourly_profile(2400.0)
    assert len(p) == 24 and set(p) == {100.0}


def test_savings_is_baseline_minus_scenario():
    base = T.daily_cost(D, [100.0] * 24)
    scen = T.daily_cost(D, [90.0] * 24)
    s = T.savings(base, scen)
    assert s.energy_cost == pytest.approx(24.2)
    assert s.demand_cost == pytest.approx(4.0)
    assert s.total_cost == pytest.approx(28.2)
    assert s.total_pct == pytest.approx(10.0)
    assert T.savings(scen, base).total_cost == pytest.approx(-28.2)  # a worse scenario is a negative saving
    assert (
        T.savings(
            T.daily_cost(T.Tariff(off_peak_rate=0, peak_rate=0, demand_charge_per_kw=0), [1.0] * 24), scen
        ).total_pct
        is None
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"currency": "usd"},
        {"currency": "US"},
        {"off_peak_rate": -0.01},
        {"peak_rate": float("nan")},
        {"demand_charge_per_kw": float("inf")},
        {"peak_start_hour": 25},
        {"peak_end_hour": -1},
        {"billing_days": 0},
        {"billing_days": 367},
    ],
)
def test_bad_tariffs_are_refused(bad):
    with pytest.raises(T.TariffError):
        T.Tariff(**bad).validate()


def test_bad_profiles_are_refused():
    with pytest.raises(T.TariffError):
        T.daily_cost(D, [1.0] * 23)
    with pytest.raises(T.TariffError):
        T.daily_cost(D, [-1.0] + [1.0] * 23)
    with pytest.raises(T.TariffError):
        T.flat_hourly_profile(-1.0)


# ------------------------------------------------------------------------------------------ summary assembly
def _fake_whatif(util, temp, stress, mode, chw):
    kwh = 2400.0 * util / 0.65  # deterministic stand-in: 2400 kWh at the default utilisation
    return {
        "inputs": {
            "utilisation": util,
            "outside_temp_C": temp,
            "water_stress": stress,
            "mode": mode,
            "chilled_water_temp_C": chw,
        },
        "mean_pue": 1.3,
        "total_energy_kwh": kwh,
        "carbon_data_is_real": False,
    }


_DEFAULTS = {
    k: SR.WHATIF_DEFAULTS[k] for k in ("utilisation", "outside_temp", "water_stress", "mode", "chilled_water_temp")
}


def test_summary_for_the_default_scenario_has_zero_savings_and_the_illustrative_label():
    r = E.compute_summary(D, dict(_DEFAULTS), whatif=_fake_whatif)
    assert r["label"] == "illustrative tariff, not a quote"
    assert r["is_default_tariff"] is True and r["origin"] == "simulated"
    assert r["scenario"]["cost"]["total_cost"] == pytest.approx(282.0)
    assert r["baseline"]["cost"]["total_cost"] == pytest.approx(282.0)
    assert r["savings"]["total_cost"] == 0.0
    assert r["carbon_data_is_real"] is False


def test_summary_savings_for_a_lower_load_scenario_and_custom_tariff_label():
    calls = []

    def counting(*a):
        calls.append(a)
        return _fake_whatif(*a)

    r = E.compute_summary(D, {**_DEFAULTS, "utilisation": 0.585}, whatif=counting)  # 90 % of baseline energy
    assert len(calls) == 2
    assert r["savings"]["total_cost"] == pytest.approx(28.2)
    assert r["savings"]["total_pct"] == pytest.approx(10.0)
    custom = E.compute_summary(T.Tariff(currency="EUR", peak_rate=0.5), dict(_DEFAULTS), whatif=_fake_whatif)
    assert custom["is_default_tariff"] is False and custom["currency"] == "EUR"
    assert "still not a quote" in custom["label"]


def test_default_scenario_runs_the_twin_once():
    calls = []
    E.compute_summary(D, dict(_DEFAULTS), whatif=lambda *a: calls.append(a) or _fake_whatif(*a))
    assert len(calls) == 1


def test_summary_refuses_an_invalid_tariff_before_any_run():
    calls = []
    with pytest.raises(T.TariffError):
        E.compute_summary(T.Tariff(billing_days=0), dict(_DEFAULTS), whatif=lambda *a: calls.append(a))
    assert calls == []
