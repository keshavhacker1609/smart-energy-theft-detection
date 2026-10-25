"""Runtime configuration. Every threshold and default lives here and can be overridden by env var."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.battery import BatteryConfig
from app.cleaning import CleaningLimits
from app.controller import ControllerRules

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")

    storage_threshold_kw: float = 160.0
    overload_threshold_kw: float = 200.0
    peak_start_hour: int = Field(18, ge=0, le=23)
    peak_end_hour: int = Field(22, ge=0, le=23)

    battery_capacity_kwh: float = Field(600.0, gt=0)
    battery_initial_soc_pct: float = Field(80.0, ge=0, le=100)
    battery_reserve_soc_pct: float = Field(20.0, ge=0, le=100)
    battery_max_charge_kw: float = Field(120.0, gt=0)
    battery_max_discharge_kw: float = Field(150.0, gt=0)
    battery_round_trip_efficiency: float = Field(0.9, gt=0, le=1)
    battery_solar_reference_wm2: float = Field(500.0, gt=0)

    horizon_hours: int = Field(24, ge=1)
    max_upload_bytes: int = Field(2_000_000, gt=0)
    max_rows: int = Field(5000, gt=0)
    max_manual_rows: int = Field(24, gt=0)
    max_impute_gap_hours: int = Field(3, ge=0)
    temp_min_c: float = -30.0
    temp_max_c: float = 55.0
    humidity_clip_tolerance_pct: float = Field(5.0, ge=0)
    irradiance_max_wm2: float = 1500.0
    irradiance_clip_tolerance_wm2: float = Field(10.0, ge=0)

    storage_backend: Literal["local", "catalyst"] = "local"
    local_data_dir: Path = BACKEND_ROOT / ".data"
    stratus_bucket: str = "telemetry-uploads"
    datastore_runs_table: str = "ForecastRuns"
    datastore_hours_table: str = "ForecastHours"

    cors_origins: list[str] = Field(default_factory=list)
    health_cache_s: float = Field(30.0, ge=0)

    @model_validator(mode="after")
    def _check_ranges(self) -> Settings:
        if self.overload_threshold_kw < self.storage_threshold_kw:
            raise ValueError("overload threshold must not be below the storage threshold")
        if self.peak_end_hour < self.peak_start_hour:
            raise ValueError("peak window must not wrap past midnight")
        return self

    @property
    def rules(self) -> ControllerRules:
        return ControllerRules(
            storage_threshold_kw=self.storage_threshold_kw,
            overload_threshold_kw=self.overload_threshold_kw,
            peak_start_hour=self.peak_start_hour,
            peak_end_hour=self.peak_end_hour,
        )

    @property
    def battery(self) -> BatteryConfig:
        return BatteryConfig(
            capacity_kwh=self.battery_capacity_kwh,
            initial_soc_pct=self.battery_initial_soc_pct,
            reserve_soc_pct=self.battery_reserve_soc_pct,
            max_charge_kw=self.battery_max_charge_kw,
            max_discharge_kw=self.battery_max_discharge_kw,
            round_trip_efficiency=self.battery_round_trip_efficiency,
            solar_reference_wm2=self.battery_solar_reference_wm2,
        )

    @property
    def cleaning(self) -> CleaningLimits:
        return CleaningLimits(
            max_rows=self.max_rows,
            max_impute_gap_hours=self.max_impute_gap_hours,
            temp_min_c=self.temp_min_c,
            temp_max_c=self.temp_max_c,
            humidity_clip_tolerance_pct=self.humidity_clip_tolerance_pct,
            irradiance_max_wm2=self.irradiance_max_wm2,
            irradiance_clip_tolerance_wm2=self.irradiance_clip_tolerance_wm2,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
