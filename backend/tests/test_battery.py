import math

import pytest

from app.battery import BatteryConfig, simulate
from app.controller import GridMode

STORAGE = GridMode.RENEWABLE_STORAGE
GRID = GridMode.MAIN_GRID
LOSSLESS = BatteryConfig(
    capacity_kwh=100,
    initial_soc_pct=50,
    reserve_soc_pct=20,
    max_charge_kw=40,
    max_discharge_kw=30,
    round_trip_efficiency=1.0,
    solar_reference_wm2=500,
)


def test_storage_mode_discharges_up_to_rate() -> None:
    (step,) = simulate([50.0], [STORAGE], [0.0], LOSSLESS)
    assert step.discharge_kw == 30
    assert step.grid_kw == 20
    assert step.soc_pct == pytest.approx(20)
    assert step.reserve_low


def test_discharge_stops_at_reserve_and_warns() -> None:
    steps = simulate([20.0, 20.0, 20.0], [STORAGE] * 3, [0.0] * 3, LOSSLESS)
    assert [s.discharge_kw for s in steps] == pytest.approx([20, 10, 0])
    assert [s.soc_pct for s in steps] == pytest.approx([30, 20, 20])
    assert [s.reserve_low for s in steps] == [False, True, True]
    assert steps[2].grid_kw == 20


def test_grid_mode_charges_scaled_by_irradiance() -> None:
    steps = simulate([100.0, 100.0, 100.0], [GRID] * 3, [0.0, 250.0, 900.0], LOSSLESS)
    assert [s.charge_kw for s in steps] == pytest.approx([0, 20, 30])
    assert steps[-1].soc_pct == pytest.approx(100)
    assert all(s.grid_kw == 100 and not s.reserve_low for s in steps)


def test_round_trip_efficiency_splits_losses() -> None:
    config = BatteryConfig(
        capacity_kwh=100,
        initial_soc_pct=50,
        reserve_soc_pct=0,
        max_charge_kw=10,
        max_discharge_kw=10,
        round_trip_efficiency=0.81,
        solar_reference_wm2=100,
    )
    charged, discharged = simulate([0.0, 9.0], [GRID, STORAGE], [100.0, 0.0], config)
    assert charged.soc_pct == pytest.approx(59)
    assert discharged.soc_pct == pytest.approx(49)


def test_initial_soc_below_reserve_never_discharges() -> None:
    config = BatteryConfig(capacity_kwh=100, initial_soc_pct=10, reserve_soc_pct=20)
    (step,) = simulate([80.0], [STORAGE], [0.0], config)
    assert step.discharge_kw == 0 and step.reserve_low and step.grid_kw == 80


def test_negative_demand_is_treated_as_zero_load() -> None:
    (step,) = simulate([-5.0], [STORAGE], [0.0], LOSSLESS)
    assert step.discharge_kw == 0 and step.grid_kw == 0


def test_lengths_must_match() -> None:
    with pytest.raises(ValueError, match="equal length"):
        simulate([1.0], [GRID, GRID], [0.0], LOSSLESS)


@pytest.mark.parametrize(
    "field",
    ["capacity_kwh", "initial_soc_pct", "reserve_soc_pct", "round_trip_efficiency", "solar_reference_wm2"],
)
def test_invalid_parameters_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        BatteryConfig(**{field: -1.0})


def test_soc_never_leaves_bounds_over_long_run() -> None:
    modes = [STORAGE if h % 24 >= 18 else GRID for h in range(24 * 7)]
    irradiance = [max(0.0, 500 * math.sin(math.pi * ((h % 24) - 6) / 12)) for h in range(24 * 7)]
    steps = simulate([200.0] * len(modes), modes, irradiance, BatteryConfig())
    assert all(20 - 1e-9 <= s.soc_pct <= 100 + 1e-9 for s in steps)
