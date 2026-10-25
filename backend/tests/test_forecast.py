from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.battery import BatteryConfig
from app.cleaning import clean
from app.controller import ControllerRules, GridMode
from app.forecast import assemble, window_hours

RULES = ControllerRules()
START = datetime(2015, 7, 1, 15)


def _frame(n: int) -> pd.DataFrame:
    stamps = pd.date_range(START, periods=n, freq="h")
    return clean(
        pd.DataFrame(
            {
                "timestamp": stamps.astype(str),
                "ambient_temp_c": 30.0,
                "humidity_pct": 50.0,
                "solar_irradiance_wm2": 100.0,
            }
        )
    ).frame


def test_summary_counts_transitions_peak_and_overloads() -> None:
    # 15:00..20:00 -> grid, grid, storage(>160), storage(peak), storage(overload), storage(peak)
    demand = np.array([150.0, 155.0, 170.0, 120.0, 214.6, 130.0])
    result = assemble(_frame(6), demand, RULES, BatteryConfig(), horizon_hours=24)
    summary = result.summary
    assert [h.mode for h in result.hours] == [GridMode.MAIN_GRID] * 2 + [GridMode.RENEWABLE_STORAGE] * 4
    assert summary.current_mode is GridMode.MAIN_GRID
    assert summary.next_transition_at == START + timedelta(hours=2)
    assert summary.next_transition_mode is GridMode.RENEWABLE_STORAGE
    assert summary.transitions == 1
    assert (summary.storage_hours, summary.grid_hours) == (4, 2)
    assert summary.peak_kw == 214.6 and summary.peak_at == START + timedelta(hours=4)
    assert summary.overload_at == [START + timedelta(hours=4)]
    assert summary.grid_energy_avoided_kwh == pytest.approx(sum(h.battery_discharge_kw for h in result.hours))


def test_events_log_switches_and_overloads() -> None:
    demand = np.array([150.0, 170.0, 150.0, 210.0])
    events = assemble(_frame(4), demand, RULES, BatteryConfig(), 24).events
    messages = [e.message for e in events]
    assert messages[0].startswith("Start in MAIN_GRID")
    assert "Switch to RENEWABLE_STORAGE at 16:00 (demand 170 kW > 160 kW)" in messages
    assert any(m.startswith("Critical overload forecast at 18:00: 210.0 kW") for m in messages)
    assert sum(e.kind == "mode" for e in events) == 4


def test_no_transition_when_mode_is_constant() -> None:
    summary = assemble(_frame(3), np.array([100.0, 100.0, 100.0]), RULES, BatteryConfig(), 24).summary
    assert summary.next_transition_at is None and summary.transitions == 0


def test_window_takes_first_24_hours_from_earliest_timestamp() -> None:
    result = assemble(_frame(30), np.full(30, 100.0), RULES, BatteryConfig(), horizon_hours=24)
    assert len(result.hours) == 30
    assert result.summary.window_hours == 24
    assert result.summary.window_end == START + timedelta(hours=23)
    assert window_hours([], 24) == []


def test_prediction_count_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected 3 predictions"):
        assemble(_frame(3), np.array([1.0]), RULES, BatteryConfig(), 24)
