"""Forecast pipeline: cleaned telemetry -> features -> QuickML -> controller -> battery -> summary."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Protocol

import numpy as np
import pandas as pd

from app.battery import BatteryConfig, simulate
from app.cleaning import ACTUAL, IMPUTED, SOURCE_ROW, CleaningLimits, Issue, QualityReport, clean
from app.controller import ControllerRules, GridMode, evaluate
from app.features import HUMIDITY, IRRADIANCE, TEMPERATURE, TIMESTAMP, build_features
from app.schemas import (
    BatteryParams,
    ForecastResult,
    ForecastRun,
    GapOut,
    HourOut,
    IssueOut,
    LogEvent,
    ModelInfo,
    QualityReportOut,
    RunSource,
    ScenarioDelta,
    SimulateResponse,
    SummaryOut,
    TelemetryRowIn,
)


class Predictor(Protocol):
    def predict(self, features: pd.DataFrame) -> np.ndarray: ...


@dataclass(frozen=True)
class ForecastEngine:
    predictor: Predictor
    rules: ControllerRules
    limits: CleaningLimits
    horizon_hours: int
    model: ModelInfo

    def run(
        self,
        raw: pd.DataFrame,
        source: RunSource,
        filename: str | None,
        battery: BatteryConfig,
    ) -> ForecastRun:
        cleaned = clean(raw, self.limits)
        frame = cleaned.frame
        predictions = self.predictor.predict(build_features(frame))
        result = assemble(frame, predictions, self.rules, battery, self.horizon_hours)
        created_at = datetime.now(UTC)
        return ForecastRun(
            id=uuid.uuid4().hex,
            created_at=created_at,
            source=source,
            filename=filename,
            quality=quality_out(cleaned.report),
            battery=BatteryParams.from_config(battery),
            model=self.model,
            hours=result.hours,
            summary=result.summary,
            events=ingest_events(cleaned.report, created_at) + result.events,
        )

    def simulate(
        self, rows: Sequence[TelemetryRowIn], temperature_offset_c: float, battery: BatteryConfig
    ) -> SimulateResponse:
        """Baseline and shifted-temperature scenario, scored in one prediction pass."""
        frame = clean(rows_frame(rows), self.limits).frame
        shifted = frame.assign(**{TEMPERATURE: frame[TEMPERATURE] + temperature_offset_c})
        features = pd.concat([build_features(frame), build_features(shifted)], ignore_index=True)
        predictions = self.predictor.predict(features)
        baseline_pred, scenario_pred = predictions[: len(frame)], predictions[len(frame) :]
        horizon = len(frame)
        baseline = assemble(frame, baseline_pred, self.rules, battery, horizon)
        scenario = assemble(shifted, scenario_pred, self.rules, battery, horizon)
        return SimulateResponse(
            baseline=baseline, scenario=scenario, delta=delta(baseline.summary, scenario.summary)
        )


def rows_frame(rows: Sequence[TelemetryRowIn]) -> pd.DataFrame:
    return pd.DataFrame([row.model_dump() for row in rows])


def assemble(
    frame: pd.DataFrame,
    predictions: np.ndarray,
    rules: ControllerRules,
    battery: BatteryConfig,
    horizon_hours: int,
) -> ForecastResult:
    if len(predictions) != len(frame):
        raise ValueError(f"expected {len(frame)} predictions, got {len(predictions)}")
    timestamps = pd.to_datetime(frame[TIMESTAMP])
    signals = [evaluate(float(d), int(ts.hour), rules) for d, ts in zip(predictions, timestamps, strict=True)]
    steps = simulate(predictions.tolist(), [s.mode for s in signals], frame[IRRADIANCE].tolist(), battery)

    hours = [
        HourOut(
            timestamp=ts.to_pydatetime(),
            source_row=int(row[SOURCE_ROW]),
            ambient_temp_c=float(row[TEMPERATURE]),
            humidity_pct=float(row[HUMIDITY]),
            solar_irradiance_wm2=float(row[IRRADIANCE]),
            imputed=list(row[IMPUTED]),
            predicted_kw=float(pred),
            actual_kw=None if pd.isna(row[ACTUAL]) else float(row[ACTUAL]),
            mode=signal.mode,
            overload=signal.overload,
            reasons=list(signal.reasons),
            soc_pct=step.soc_pct,
            battery_discharge_kw=step.discharge_kw,
            battery_charge_kw=step.charge_kw,
            grid_kw=step.grid_kw,
            reserve_low=step.reserve_low,
        )
        for (_, row), ts, pred, signal, step in zip(
            frame.iterrows(), timestamps, predictions, signals, steps, strict=True
        )
    ]
    window = window_hours(hours, horizon_hours)
    return ForecastResult(hours=hours, summary=summarize(window, hours), events=dispatch_events(window))


def window_hours(hours: Sequence[HourOut], horizon_hours: int) -> list[HourOut]:
    """The dashboard window: rows within `horizon_hours` of the earliest timestamp."""
    if not hours:
        return []
    end = hours[0].timestamp + pd.Timedelta(hours=horizon_hours)
    return [h for h in hours if h.timestamp < end]


def summarize(window: Sequence[HourOut], all_hours: Sequence[HourOut]) -> SummaryOut:
    first = window[0]
    switch = next((h for h in window if h.mode is not first.mode), None)
    peak = max(window, key=lambda h: h.predicted_kw)
    with_actual = [h for h in all_hours if h.actual_kw is not None]
    actual_rmse = (
        float(
            np.sqrt(
                np.mean([(h.predicted_kw - h.actual_kw) ** 2 for h in with_actual if h.actual_kw is not None])
            )
        )
        if with_actual
        else None
    )
    socs = [h.soc_pct for h in window]
    return SummaryOut(
        window_start=first.timestamp,
        window_end=window[-1].timestamp,
        window_hours=len(window),
        current_mode=first.mode,
        next_transition_at=switch.timestamp if switch else None,
        next_transition_mode=switch.mode if switch else None,
        transitions=sum(a.mode is not b.mode for a, b in pairwise(window)),
        storage_hours=sum(h.mode is GridMode.RENEWABLE_STORAGE for h in window),
        grid_hours=sum(h.mode is GridMode.MAIN_GRID for h in window),
        overload_hours=sum(h.overload for h in window),
        overload_at=[h.timestamp for h in window if h.overload],
        peak_kw=peak.predicted_kw,
        peak_at=peak.timestamp,
        grid_energy_avoided_kwh=float(sum(h.battery_discharge_kw for h in window)),
        reserve_low_hours=sum(h.reserve_low for h in window),
        min_soc_pct=min(socs),
        final_soc_pct=socs[-1],
        actual_rmse_kw=actual_rmse,
        actual_rows=len(with_actual),
    )


def delta(baseline: SummaryOut, scenario: SummaryOut) -> ScenarioDelta:
    return ScenarioDelta(
        peak_kw=scenario.peak_kw - baseline.peak_kw,
        overload_hours=scenario.overload_hours - baseline.overload_hours,
        storage_hours=scenario.storage_hours - baseline.storage_hours,
        transitions=scenario.transitions - baseline.transitions,
        grid_energy_avoided_kwh=scenario.grid_energy_avoided_kwh - baseline.grid_energy_avoided_kwh,
        reserve_low_hours=scenario.reserve_low_hours - baseline.reserve_low_hours,
        min_soc_pct=scenario.min_soc_pct - baseline.min_soc_pct,
    )


def dispatch_events(window: Sequence[HourOut]) -> list[LogEvent]:
    events: list[LogEvent] = []
    previous: HourOut | None = None
    for hour in window:
        clock = f"{hour.timestamp:%H:%M}"
        if previous is None:
            events.append(_event(hour.timestamp, "info", "mode", f"Start in {hour.mode} ({hour.reasons[0]})"))
        elif hour.mode is not previous.mode:
            events.append(
                _event(
                    hour.timestamp, "info", "mode", f"Switch to {hour.mode} at {clock} ({hour.reasons[0]})"
                )
            )
        if hour.overload:
            events.append(
                _event(
                    hour.timestamp,
                    "critical",
                    "overload",
                    f"Critical overload forecast at {clock}: {hour.predicted_kw:.1f} kW",
                )
            )
        if hour.reserve_low and not (previous and previous.reserve_low):
            events.append(
                _event(
                    hour.timestamp,
                    "warning",
                    "battery_reserve_low",
                    f"BATTERY_RESERVE_LOW at {clock}: state of charge {hour.soc_pct:.1f}% at reserve "
                    f"while storage mode is required; shortfall drawn from grid",
                )
            )
        previous = hour
    return events


def ingest_events(report: QualityReport, at: datetime) -> list[LogEvent]:
    events = [
        _event(
            at,
            "info",
            "ingest",
            f"Received {report.rows_received} rows, accepted {report.rows_accepted}, "
            f"rejected {report.rows_rejected}",
            phase="ingest",
        )
    ]
    counts = Counter((issue.kind, issue.column or "row") for issue in report.issues)
    for (kind, column), count in sorted(counts.items()):
        level = "warning" if kind in {"gap_too_large", "invalid_timestamp", "duplicate_timestamp"} else "info"
        events.append(
            _event(at, level, kind, f"{kind.replace('_', ' ')}: {count} in {column}", phase="ingest")
        )
    for gap in report.gaps:
        events.append(
            _event(
                at,
                "warning",
                "sequence_gap",
                f"{gap.missing_hours} h missing between {gap.after:%Y-%m-%d %H:%M} "
                f"and {gap.before:%Y-%m-%d %H:%M}",
                phase="ingest",
            )
        )
    return events


def _event(at: datetime, level: str, kind: str, message: str, phase: str = "dispatch") -> LogEvent:
    return LogEvent.model_validate(
        {"at": at, "phase": phase, "level": level, "kind": kind, "message": message}
    )


def quality_issue(issue: Issue) -> IssueOut:
    return IssueOut(
        row=issue.row, column=issue.column, kind=issue.kind, detail=issue.detail, action=issue.action
    )


def quality_out(report: QualityReport) -> QualityReportOut:
    return QualityReportOut(
        rows_received=report.rows_received,
        rows_accepted=report.rows_accepted,
        rows_imputed=report.rows_imputed,
        rows_rejected=report.rows_rejected,
        values_imputed=report.values_imputed,
        values_clipped=report.values_clipped,
        duplicates_removed=report.duplicates_removed,
        columns_renamed=report.columns_renamed,
        gaps=[
            GapOut(
                after=g.after.to_pydatetime(), before=g.before.to_pydatetime(), missing_hours=g.missing_hours
            )
            for g in report.gaps
        ],
        issues=[quality_issue(i) for i in report.issues],
        issues_truncated=report.issues_truncated,
    )
