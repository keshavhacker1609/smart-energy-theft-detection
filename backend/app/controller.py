"""Grid transition controller: the specification rules, nothing more.

RENEWABLE_STORAGE if demand > storage threshold or the hour is inside the
peak window (inclusive); MAIN_GRID otherwise. A critical overload is raised
when demand >= overload threshold, independently of the mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class GridMode(StrEnum):
    MAIN_GRID = "MAIN_GRID"
    RENEWABLE_STORAGE = "RENEWABLE_STORAGE"


@dataclass(frozen=True)
class ControllerRules:
    storage_threshold_kw: float = 160.0
    overload_threshold_kw: float = 200.0
    peak_start_hour: int = 18
    peak_end_hour: int = 22


DEFAULT_RULES = ControllerRules()


@dataclass(frozen=True)
class Signal:
    mode: GridMode
    overload: bool
    reasons: tuple[str, ...]


def _kw(value: float) -> str:
    return f"{value:.6g} kW"


def evaluate(demand_kw: float, hour: int, rules: ControllerRules = DEFAULT_RULES) -> Signal:
    """Signal for one forecast hour from predicted demand and the timestamp's hour."""
    if not math.isfinite(demand_kw):
        raise ValueError(f"demand must be finite, got {demand_kw}")
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be within 0-23, got {hour}")

    above_threshold = demand_kw > rules.storage_threshold_kw
    in_peak_window = rules.peak_start_hour <= hour <= rules.peak_end_hour
    overload = demand_kw >= rules.overload_threshold_kw

    reasons: list[str] = []
    if above_threshold:
        reasons.append(f"demand {_kw(demand_kw)} > {_kw(rules.storage_threshold_kw)}")
    if in_peak_window:
        reasons.append(
            f"hour {hour:02d}:00 in peak window {rules.peak_start_hour:02d}:00-{rules.peak_end_hour:02d}:00"
        )
    if not reasons:
        reasons.append(
            f"demand {_kw(demand_kw)} <= {_kw(rules.storage_threshold_kw)} and hour {hour:02d}:00 "
            f"outside peak window"
        )
    if overload:
        reasons.append(f"critical overload: demand {_kw(demand_kw)} >= {_kw(rules.overload_threshold_kw)}")

    mode = GridMode.RENEWABLE_STORAGE if above_threshold or in_peak_window else GridMode.MAIN_GRID
    return Signal(mode=mode, overload=overload, reasons=tuple(reasons))
