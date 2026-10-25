"""Battery state-of-charge simulation alongside the controller's dispatch.

Advisory only: it never changes the mode chosen by the controller. In storage
mode the battery serves as much demand as its discharge rate and reserve allow
(the rest comes from the grid) and flags BATTERY_RESERVE_LOW when the state of
charge sits at the reserve; in grid mode it charges from solar, scaled by
irradiance. Round-trip losses are split evenly between charge and discharge.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.controller import GridMode

STEP_HOURS = 1.0
RESERVE_EPSILON_KWH = 1e-9


@dataclass(frozen=True)
class BatteryConfig:
    capacity_kwh: float = 600.0
    initial_soc_pct: float = 80.0
    reserve_soc_pct: float = 20.0
    max_charge_kw: float = 120.0
    max_discharge_kw: float = 150.0
    round_trip_efficiency: float = 0.9
    solar_reference_wm2: float = 500.0

    def __post_init__(self) -> None:
        checks = {
            "capacity_kwh": self.capacity_kwh > 0,
            "initial_soc_pct": 0 <= self.initial_soc_pct <= 100,
            "reserve_soc_pct": 0 <= self.reserve_soc_pct <= 100,
            "max_charge_kw": self.max_charge_kw >= 0,
            "max_discharge_kw": self.max_discharge_kw >= 0,
            "round_trip_efficiency": 0 < self.round_trip_efficiency <= 1,
            "solar_reference_wm2": self.solar_reference_wm2 > 0,
        }
        invalid = [name for name, ok in checks.items() if not ok]
        if invalid:
            raise ValueError(f"invalid battery parameters: {', '.join(invalid)}")


@dataclass(frozen=True)
class BatteryStep:
    soc_pct: float
    discharge_kw: float
    charge_kw: float
    grid_kw: float
    reserve_low: bool


def simulate(
    demand_kw: Sequence[float],
    modes: Sequence[GridMode],
    irradiance_wm2: Sequence[float],
    config: BatteryConfig,
) -> list[BatteryStep]:
    """Hour-by-hour state of charge; one step per forecast hour, SoC reported at end of hour."""
    if not len(demand_kw) == len(modes) == len(irradiance_wm2):
        raise ValueError("demand, modes and irradiance must have equal length")

    one_way = math.sqrt(config.round_trip_efficiency)
    capacity = config.capacity_kwh
    reserve = capacity * config.reserve_soc_pct / 100
    energy = capacity * config.initial_soc_pct / 100
    steps: list[BatteryStep] = []

    for demand, mode, irradiance in zip(demand_kw, modes, irradiance_wm2, strict=True):
        load = max(0.0, float(demand))
        discharge = charge = 0.0
        reserve_low = False
        if mode is GridMode.RENEWABLE_STORAGE:
            available = max(0.0, energy - reserve) * one_way / STEP_HOURS
            wanted = min(load, config.max_discharge_kw)
            discharge = min(wanted, available)
            energy -= discharge * STEP_HOURS / one_way
            reserve_low = energy <= reserve + RESERVE_EPSILON_KWH
        else:
            solar_fraction = min(1.0, max(0.0, float(irradiance)) / config.solar_reference_wm2)
            headroom = max(0.0, capacity - energy) / one_way / STEP_HOURS
            charge = min(config.max_charge_kw * solar_fraction, headroom)
            energy += charge * STEP_HOURS * one_way
        steps.append(
            BatteryStep(
                soc_pct=100 * energy / capacity,
                discharge_kw=discharge,
                charge_kw=charge,
                grid_kw=load - discharge,
                reserve_low=reserve_low,
            )
        )
    return steps
