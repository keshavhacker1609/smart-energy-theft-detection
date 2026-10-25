import math

import pytest

from app.controller import ControllerRules, GridMode, evaluate

STORAGE = GridMode.RENEWABLE_STORAGE
GRID = GridMode.MAIN_GRID


@pytest.mark.parametrize(
    ("demand", "hour", "mode", "overload"),
    [
        # demand boundaries outside the peak window
        (160.0, 12, GRID, False),
        (160.01, 12, STORAGE, False),
        (199.99, 12, STORAGE, False),
        (200.0, 12, STORAGE, True),
        (159.99, 12, GRID, False),
        # hour boundaries with low demand
        (100.0, 17, GRID, False),
        (100.0, 18, STORAGE, False),
        (100.0, 22, STORAGE, False),
        (100.0, 23, GRID, False),
        (100.0, 0, GRID, False),
        # peak window with low demand, high demand outside window
        (50.0, 20, STORAGE, False),
        (180.0, 3, STORAGE, False),
        # overload inside and outside the window
        (214.6, 19, STORAGE, True),
        (205.0, 9, STORAGE, True),
        (200.0, 18, STORAGE, True),
        (160.0, 22, STORAGE, False),
        (160.0, 23, GRID, False),
    ],
)
def test_spec_rules(demand: float, hour: int, mode: GridMode, overload: bool) -> None:
    signal = evaluate(demand, hour)
    assert signal.mode is mode
    assert signal.overload is overload


def test_reasons_name_each_rule_that_fired() -> None:
    signal = evaluate(214.6, 19)
    assert signal.reasons == (
        "demand 214.6 kW > 160 kW",
        "hour 19:00 in peak window 18:00-22:00",
        "critical overload: demand 214.6 kW >= 200 kW",
    )


def test_grid_reason_explains_both_conditions() -> None:
    (reason,) = evaluate(160.0, 17).reasons
    assert reason == "demand 160 kW <= 160 kW and hour 17:00 outside peak window"


def test_reason_shows_enough_precision_near_threshold() -> None:
    assert evaluate(160.004, 12).reasons[0] == "demand 160.004 kW > 160 kW"


def test_peak_window_reason_alone_for_low_demand() -> None:
    assert evaluate(90.0, 18).reasons == ("hour 18:00 in peak window 18:00-22:00",)


def test_rules_are_configurable() -> None:
    rules = ControllerRules(
        storage_threshold_kw=100, overload_threshold_kw=120, peak_start_hour=7, peak_end_hour=8
    )
    assert evaluate(110, 12, rules).mode is STORAGE
    assert evaluate(90, 7, rules).mode is STORAGE
    assert evaluate(90, 18, rules).mode is GRID
    assert evaluate(120, 12, rules).overload


@pytest.mark.parametrize("demand", [math.nan, math.inf, -math.inf])
def test_rejects_non_finite_demand(demand: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        evaluate(demand, 12)


@pytest.mark.parametrize("hour", [-1, 24])
def test_rejects_invalid_hour(hour: int) -> None:
    with pytest.raises(ValueError, match="hour"):
        evaluate(100.0, hour)
