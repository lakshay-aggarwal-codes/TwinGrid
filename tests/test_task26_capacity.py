"""Task 26: deterministic tests for the capacity planner (headroom and the "add N racks at X kW" what-if).

The planner tests run the real digital twin (physics v1, fixed start time, no randomness), so the golden numbers are the
twin's own. A fake twin covers physics legacy-0 (no cooling capacity) and the exact arguments of the candidate twin.
The last section needs FastAPI and is skipped where it is not installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from types import SimpleNamespace

import pytest

from src.capacity import planner as P
from src.digital_twin import DigitalTwin

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
make_twin = partial(DigitalTwin, physics_version="1", start_time=START)
DEFAULT = P.Scenario(utilisation=0.65, outside_temp=22.0, water_stress=0.0, mode="auto", chilled_water_temp=7.0)


# ----------------------------------------------------------------------------- pure classification


@pytest.mark.parametrize(
    "headroom,limit,expected",
    [
        (100.0, 500.0, P.OK),
        (50.0, 500.0, P.OK),  # exactly 10 % is still ok
        (49.9, 500.0, P.TIGHT),
        (0.0, 500.0, P.TIGHT),
        (-0.1, 500.0, P.EXCEEDED),
        (None, 500.0, P.UNKNOWN),
        (10.0, None, P.UNKNOWN),
        (10.0, 0.0, P.UNKNOWN),
    ],
)
def test_classify_share(headroom, limit, expected):
    assert P.classify_share(headroom, limit) == expected


@pytest.mark.parametrize(
    "margin,expected",
    [(8.0, P.OK), (3.0, P.OK), (2.99, P.TIGHT), (0.0, P.TIGHT), (-0.01, P.EXCEEDED), (float("nan"), P.EXCEEDED)],
)
def test_classify_margin(margin, expected):
    assert P.classify_margin(margin) == expected


def test_overall_is_the_worst_known_and_unknown_is_ignored():
    assert P.overall_status([P.OK, P.OK, P.OK]) == P.OK
    assert P.overall_status([P.OK, P.TIGHT, P.OK]) == P.TIGHT
    assert P.overall_status([P.TIGHT, P.EXCEEDED, P.OK]) == P.EXCEEDED
    assert P.overall_status([P.OK, P.UNKNOWN, P.OK]) == P.OK
    assert P.overall_status([P.UNKNOWN, P.UNKNOWN, P.UNKNOWN]) == P.OK
    assert [P.verdict_for(s) for s in (P.OK, P.TIGHT, P.EXCEEDED)] == [P.FITS, P.FITS_TIGHT, P.DOES_NOT_FIT]


def test_racks_that_fit_rounds_down_and_never_goes_negative():
    assert P.racks_that_fit(105.0, 8.0) == 13
    assert P.racks_that_fit(7.99, 8.0) == 0
    assert P.racks_that_fit(-55.0, 8.0) == 0
    assert P.racks_that_fit(None, 8.0) is None


@pytest.mark.parametrize(
    "racks,kw",
    [(-1, 8.0), (P.MAX_ADD_RACKS + 1, 8.0), (1.5, 8.0), (True, 8.0), (1, 0.0), (1, 60.1), (1, float("nan")), (1, "8")],
)
def test_plan_validation_rejects_out_of_bounds(racks, kw):
    with pytest.raises(ValueError):
        P.Plan(racks, kw).validate()


def test_plan_accepts_its_bounds():
    assert P.Plan(0, 0.1).validate().added_kw == 0.0
    assert P.Plan(P.MAX_ADD_RACKS, 60.0).validate().added_kw == 12000.0


# ----------------------------------------------------------------------------- the real twin: golden numbers


def test_labels_are_stated():
    r = P.evaluate(make_twin, DEFAULT, P.Plan(0, 8.0))
    assert r["label"] == "model-based estimate"
    assert r["origin"] == "simulated"
    assert "no per-rack or per-zone" in r["basis"]


def test_baseline_golden_numbers():
    b = P.evaluate(make_twin, DEFAULT, P.Plan(0, 8.0))["baseline"]
    assert b["it_power_kw"] == pytest.approx(395.0)  # 0.4 x 500 + 0.6 x 0.65 x 500
    assert b["power_limit_kw"] == 500.0
    assert b["power_headroom_kw"] == pytest.approx(105.0)
    assert b["cooling_capacity_kw"] == pytest.approx(550.0)  # 1.1 x rated IT power, not derated at 22 C
    assert b["cooling_headroom_kw"] == pytest.approx(155.0)
    assert b["thermal_margin_C"] == pytest.approx(8.2626, abs=1e-3)  # 45 C outlet limit - 36.7374 C
    assert b["inlet_margin_C"] == pytest.approx(9.0)  # inlet held at the 18 C floor, limit 27 C
    assert b["status"] == {"power": "ok", "cooling": "ok", "thermal": "ok"}
    assert b["overall"] == P.OK


def test_zero_racks_changes_nothing():
    r = P.evaluate(make_twin, DEFAULT, P.Plan(0, 8.0))
    assert r["with_plan"] == r["baseline"]
    assert r["verdict"] == P.FITS
    assert r["plan"] == {"add_racks": 0, "kw_per_rack": 8.0, "added_kw": 0.0}


def test_same_inputs_give_the_identical_answer():
    a = P.evaluate(make_twin, DEFAULT, P.Plan(7, 6.5))
    b = P.evaluate(make_twin, DEFAULT, P.Plan(7, 6.5))
    assert a == b


def test_ten_racks_at_8_kw_fit_with_little_margin():
    r = P.evaluate(make_twin, DEFAULT, P.Plan(10, 8.0))
    c = r["with_plan"]
    assert c["it_power_kw"] == pytest.approx(475.0)
    assert c["power_headroom_kw"] == pytest.approx(25.0)  # 5 % of 500 kW: tight
    assert c["cooling_headroom_kw"] == pytest.approx(75.0)
    assert c["status"] == {"power": "tight", "cooling": "ok", "thermal": "ok"}
    assert r["verdict"] == P.FITS_TIGHT


def test_twenty_racks_at_8_kw_do_not_fit():
    r = P.evaluate(make_twin, DEFAULT, P.Plan(20, 8.0))
    c = r["with_plan"]
    assert c["it_power_kw"] == pytest.approx(555.0)
    assert c["power_headroom_kw"] == pytest.approx(-55.0)
    assert c["cooling_headroom_kw"] == pytest.approx(-5.0)
    assert c["status"]["power"] == P.EXCEEDED and c["status"]["cooling"] == P.EXCEEDED
    assert r["verdict"] == P.DOES_NOT_FIT
    # The baseline is untouched by the plan.
    assert r["baseline"]["power_headroom_kw"] == pytest.approx(105.0)


def test_racks_that_fit_counts_power_and_cooling_only():
    f = P.evaluate(make_twin, DEFAULT, P.Plan(0, 8.0))["racks_that_fit"]
    assert f["by_power"] == 13  # floor(105 / 8)
    assert f["by_cooling"] == 19  # floor(155 / 8)
    assert f["limit"] == 13
    assert "thermal" in f["note"]


def test_more_added_load_never_improves_any_margin():
    prev = None
    for n in (0, 5, 10, 15, 20, 30):
        c = P.evaluate(make_twin, DEFAULT, P.Plan(n, 8.0))["with_plan"]
        now = (c["power_headroom_kw"], c["cooling_headroom_kw"], c["thermal_margin_C"])
        if prev is not None:
            assert all(a <= b + 1e-9 for a, b in zip(now, prev))
        prev = now


def test_hot_day_derates_the_cooling_capacity():
    hot = P.Scenario(0.65, 45.0, 0.0, "auto", 7.0)
    b = P.evaluate(make_twin, hot, P.Plan(0, 8.0))["baseline"]
    assert b["cooling_capacity_kw"] == pytest.approx(495.0)  # 550 x (1 - 0.01 x (45 - 35))
    assert b["cooling_headroom_kw"] == pytest.approx(100.0)


def test_fixed_cooling_mode_is_respected():
    s = P.Scenario(0.65, 22.0, 0.0, "closed_loop", 7.0)
    assert P.evaluate(make_twin, s, P.Plan(0, 8.0))["baseline"]["cooling_mode"] == "closed_loop"


# ----------------------------------------------------------------------------- a fake twin


class FakeTwin:
    """Records how it was built. ``capacity`` None mimics physics legacy-0 (no finite cooling plant)."""

    built: list[dict] = []
    capacity: float | None = 550.0

    def __init__(self, **kw):
        type(self).built.append(kw)
        self._max_it_power_kw = kw.get("max_it_power_kw", 500.0)
        self._cooling_capacity_design_kw = kw.get("cooling_capacity_kw", 550.0)
        self._idle_power_fraction = 0.4
        self.last_balance: dict = {}

    def select_cooling_mode(self, outside, stress):
        from src.digital_twin import CoolingMode

        return CoolingMode.CLOSED_LOOP

    def compute_it_power(self, u):
        return self._idle_power_fraction * self._max_it_power_kw + 0.6 * u * self._max_it_power_kw

    def step(self, action):
        it = self.compute_it_power(action["utilisation"])
        cap = type(self).capacity
        self.last_balance = {} if cap is None else {"capacity_kw": cap, "heat_unremoved_kw": max(0.0, it - cap)}
        from src.digital_twin import CoolingMode

        return SimpleNamespace(
            it_power_kw=it,
            cooling_power_kw=it * 0.2,
            total_power_kw=it * 1.2,
            pue=1.2,
            server_inlet_temp_C=20.0,
            server_outlet_temp_C=30.0 + it / 100.0,
            cooling_mode=CoolingMode.CLOSED_LOOP,
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeTwin.built = []
    FakeTwin.capacity = 550.0
    yield


def test_candidate_twin_keeps_the_design_cooling_capacity_and_reaches_the_target_load():
    r = P.evaluate(FakeTwin, DEFAULT, P.Plan(20, 8.0))
    base_kw, cand_kw = FakeTwin.built
    assert "max_it_power_kw" not in base_kw  # the baseline is the twin as configured
    assert cand_kw["cooling_capacity_kw"] == 550.0  # not enlarged with the load
    assert cand_kw["max_it_power_kw"] == pytest.approx(555.0)  # base IT 395 + 160 kW, above the 500 kW rating
    assert cand_kw["initial_chilled_water_temp_C"] == 7.0
    assert r["with_plan"]["it_power_kw"] == pytest.approx(555.0)


def test_below_the_rating_the_candidate_keeps_the_rated_size():
    P.evaluate(FakeTwin, DEFAULT, P.Plan(5, 8.0))
    assert FakeTwin.built[1]["max_it_power_kw"] == 500.0


def test_no_cooling_model_means_cooling_is_unknown_not_ok_or_exceeded():
    FakeTwin.capacity = None  # legacy-0
    r = P.evaluate(FakeTwin, DEFAULT, P.Plan(10, 8.0))
    c = r["with_plan"]
    assert c["cooling_capacity_kw"] is None and c["cooling_headroom_kw"] is None
    assert c["status"]["cooling"] == P.UNKNOWN
    assert r["racks_that_fit"]["by_cooling"] is None
    assert r["racks_that_fit"]["limit"] == r["racks_that_fit"]["by_power"]


def test_unremoved_heat_reported_by_the_twin_marks_cooling_exceeded():
    FakeTwin.capacity = 400.0  # base IT is 395, so the base fits, the candidate (475) cannot be removed
    r = P.evaluate(FakeTwin, DEFAULT, P.Plan(10, 8.0))
    assert r["baseline"]["status"]["cooling"] != P.EXCEEDED
    assert r["with_plan"]["status"]["cooling"] == P.EXCEEDED


def test_invalid_plan_is_rejected_before_any_twin_is_built():
    with pytest.raises(ValueError):
        P.evaluate(FakeTwin, DEFAULT, P.Plan(-1, 8.0))
    assert FakeTwin.built == []


# ----------------------------------------------------------------------------- the plugin (needs FastAPI)


def test_plugin_wraps_the_planner_and_defaults_its_rate_limit(monkeypatch):
    from api.plugins import capacity as C  # a hard import: FastAPI is a locked runtime dependency

    assert C.DEFAULT_LIMIT == "12/minute"
    monkeypatch.delenv("RATE_LIMIT_CAPACITY", raising=False)
    assert C._limit() == "12/minute"
    monkeypatch.setenv("RATE_LIMIT_CAPACITY", "3/minute")
    assert C._limit() == "3/minute"
    out = C.compute_headroom(DEFAULT, P.Plan(10, 8.0), make_twin=make_twin)
    assert out == P.evaluate(make_twin, DEFAULT, P.Plan(10, 8.0))
    assert C.router.routes[0].path == "/api/capacity/headroom"
