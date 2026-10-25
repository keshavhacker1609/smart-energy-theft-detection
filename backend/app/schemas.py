"""Request and response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.battery import BatteryConfig
from app.controller import GridMode

RunSource = Literal["upload", "manual"]
TEMPERATURE_OFFSET_LIMIT_C = 10.0


class Model(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class TelemetryRowIn(Model):
    timestamp: str = Field(min_length=1, max_length=64)
    ambient_temp_c: float | None = None
    humidity_pct: float | None = None
    solar_irradiance_wm2: float | None = None


class BatteryParams(Model):
    capacity_kwh: float = Field(gt=0, le=100_000)
    initial_soc_pct: float = Field(ge=0, le=100)
    reserve_soc_pct: float = Field(ge=0, le=100)
    max_charge_kw: float = Field(ge=0, le=100_000)
    max_discharge_kw: float = Field(ge=0, le=100_000)
    round_trip_efficiency: float = Field(gt=0, le=1)
    solar_reference_wm2: float = Field(gt=0, le=2000)

    def to_config(self) -> BatteryConfig:
        return BatteryConfig(**self.model_dump())

    @classmethod
    def from_config(cls, config: BatteryConfig) -> BatteryParams:
        return cls(
            capacity_kwh=config.capacity_kwh,
            initial_soc_pct=config.initial_soc_pct,
            reserve_soc_pct=config.reserve_soc_pct,
            max_charge_kw=config.max_charge_kw,
            max_discharge_kw=config.max_discharge_kw,
            round_trip_efficiency=config.round_trip_efficiency,
            solar_reference_wm2=config.solar_reference_wm2,
        )


class ManualForecastRequest(Model):
    rows: list[TelemetryRowIn] = Field(min_length=1)
    battery: BatteryParams | None = None


class SimulateRequest(Model):
    rows: list[TelemetryRowIn] = Field(min_length=1, max_length=168)
    temperature_offset_c: float = Field(0.0, ge=-TEMPERATURE_OFFSET_LIMIT_C, le=TEMPERATURE_OFFSET_LIMIT_C)
    battery: BatteryParams | None = None


class IssueOut(Model):
    row: int | None
    column: str | None
    kind: str
    detail: str
    action: str


class GapOut(Model):
    after: datetime
    before: datetime
    missing_hours: int


class QualityReportOut(Model):
    rows_received: int
    rows_accepted: int
    rows_imputed: int
    rows_rejected: int
    values_imputed: int
    values_clipped: int
    duplicates_removed: int
    columns_renamed: dict[str, str]
    gaps: list[GapOut]
    issues: list[IssueOut]
    issues_truncated: int


class HourOut(Model):
    timestamp: datetime
    source_row: int
    ambient_temp_c: float
    humidity_pct: float
    solar_irradiance_wm2: float
    imputed: list[str]
    predicted_kw: float
    actual_kw: float | None
    mode: GridMode
    overload: bool
    reasons: list[str]
    soc_pct: float
    battery_discharge_kw: float
    battery_charge_kw: float
    grid_kw: float
    reserve_low: bool


class SummaryOut(Model):
    window_start: datetime
    window_end: datetime
    window_hours: int
    current_mode: GridMode
    next_transition_at: datetime | None
    next_transition_mode: GridMode | None
    transitions: int
    storage_hours: int
    grid_hours: int
    overload_hours: int
    overload_at: list[datetime]
    peak_kw: float
    peak_at: datetime
    grid_energy_avoided_kwh: float
    reserve_low_hours: int
    min_soc_pct: float
    final_soc_pct: float
    actual_rmse_kw: float | None
    actual_rows: int


class LogEvent(Model):
    at: datetime
    phase: Literal["ingest", "dispatch"]
    level: Literal["info", "warning", "critical"]
    kind: str
    message: str


class ModelInfo(Model):
    name: str
    validation_rmse_kw: float


class ForecastResult(Model):
    hours: list[HourOut]
    summary: SummaryOut
    events: list[LogEvent]


class ForecastRun(ForecastResult):
    id: str
    created_at: datetime
    source: RunSource
    filename: str | None
    quality: QualityReportOut
    battery: BatteryParams
    model: ModelInfo
    persisted: bool = False
    storage_warning: str | None = None


class RunListItem(Model):
    id: str
    created_at: datetime
    source: RunSource
    filename: str | None
    rows: int
    window_start: datetime
    current_mode: GridMode
    peak_kw: float
    overload_hours: int
    transitions: int


class ScenarioDelta(Model):
    peak_kw: float
    overload_hours: int
    storage_hours: int
    transitions: int
    grid_energy_avoided_kwh: float
    reserve_low_hours: int
    min_soc_pct: float


class SimulateResponse(Model):
    baseline: ForecastResult
    scenario: ForecastResult
    delta: ScenarioDelta


class ComponentHealth(Model):
    ok: bool
    detail: str
    latency_ms: float | None = None


class HealthOut(Model):
    status: Literal["ok", "degraded"]
    quickml: ComponentHealth
    storage: ComponentHealth


class ConfigOut(Model):
    storage_threshold_kw: float
    overload_threshold_kw: float
    peak_start_hour: int
    peak_end_hour: int
    horizon_hours: int
    max_manual_rows: int
    max_upload_bytes: int
    temperature_offset_range_c: tuple[float, float]
    battery: BatteryParams
    model: ModelInfo


class ErrorOut(Model):
    detail: str
    issues: list[IssueOut] = Field(default_factory=list)
    retryable: bool = False
