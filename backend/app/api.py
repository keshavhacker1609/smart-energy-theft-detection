"""HTTP routes. Dependencies are read from app.state so tests can inject fakes."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError

from app.cleaning import read_csv
from app.config import Settings
from app.features import build_features
from app.forecast import ForecastEngine, Predictor, rows_frame
from app.quickml_client import QuickMLError
from app.schemas import (
    TEMPERATURE_OFFSET_LIMIT_C,
    BatteryParams,
    ComponentHealth,
    ConfigOut,
    ErrorOut,
    ForecastRun,
    HealthOut,
    ManualForecastRequest,
    ModelInfo,
    RunListItem,
    SimulateRequest,
    SimulateResponse,
)
from app.storage import RunStore, StorageError

log = logging.getLogger("gridcast.api")
router = APIRouter(prefix="/api")

PROBE_ROW = {
    "timestamp": "2015-07-01 12:00:00",
    "ambient_temp_c": 25.0,
    "humidity_pct": 50.0,
    "solar_irradiance_wm2": 300.0,
}
ERRORS: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorOut, "description": "Input failed validation or cleaning"},
    502: {"model": ErrorOut, "description": "QuickML endpoint failed"},
    503: {"model": ErrorOut, "description": "A dependency is not configured or unavailable"},
}


class ServiceUnavailableError(Exception):
    def __init__(self, detail: str, retryable: bool = True) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retryable = retryable


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _model(request: Request) -> ModelInfo:
    model: ModelInfo = request.app.state.model_info
    return model


def _predictor(request: Request) -> Predictor:
    predictor: Predictor | None = request.app.state.predictor
    if predictor is None:
        reason = request.app.state.predictor_error or "not configured"
        raise ServiceUnavailableError(f"Forecast model endpoint unavailable: {reason}", retryable=False)
    return predictor


def _store(request: Request) -> RunStore:
    store: RunStore = request.app.state.store_factory(request)
    return store


def _engine(request: Request) -> ForecastEngine:
    settings = _settings(request)
    return ForecastEngine(
        predictor=_predictor(request),
        rules=settings.rules,
        limits=settings.cleaning,
        horizon_hours=settings.horizon_hours,
        model=_model(request),
    )


def _battery(params: BatteryParams | None, settings: Settings) -> BatteryParams:
    return params or BatteryParams.from_config(settings.battery)


def _persist(request: Request, run: ForecastRun, raw: bytes | None) -> ForecastRun:
    """Persist best-effort: a storage outage must not hide a computed forecast."""
    try:
        _store(request).save(run, raw)
    except StorageError as exc:
        log.warning("run %s not persisted: %s", run.id, exc)
        return run.model_copy(update={"persisted": False, "storage_warning": str(exc)})
    return run.model_copy(update={"persisted": True})


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    state = request.app.state
    settings = _settings(request)
    cached = getattr(state, "health_cache", None)
    if cached and time.monotonic() - cached[0] < settings.health_cache_s:
        result: HealthOut = cached[1]
        return result

    quickml = _check(lambda: _predictor(request).predict(build_features(pd.DataFrame([PROBE_ROW]))))
    storage = _check(lambda: _store(request).check())
    result = HealthOut(
        status="ok" if quickml.ok and storage.ok else "degraded", quickml=quickml, storage=storage
    )
    state.health_cache = (time.monotonic(), result)
    return result


def _check(probe: Any) -> ComponentHealth:
    started = time.perf_counter()
    try:
        probe()
    except (ServiceUnavailableError, QuickMLError, StorageError) as exc:
        return ComponentHealth(ok=False, detail=str(exc))
    return ComponentHealth(
        ok=True, detail="reachable", latency_ms=round((time.perf_counter() - started) * 1000, 1)
    )


@router.get("/config", response_model=ConfigOut)
def config(request: Request) -> ConfigOut:
    settings = _settings(request)
    return ConfigOut(
        storage_threshold_kw=settings.storage_threshold_kw,
        overload_threshold_kw=settings.overload_threshold_kw,
        peak_start_hour=settings.peak_start_hour,
        peak_end_hour=settings.peak_end_hour,
        horizon_hours=settings.horizon_hours,
        max_manual_rows=settings.max_manual_rows,
        max_upload_bytes=settings.max_upload_bytes,
        temperature_offset_range_c=(-TEMPERATURE_OFFSET_LIMIT_C, TEMPERATURE_OFFSET_LIMIT_C),
        battery=BatteryParams.from_config(settings.battery),
        model=_model(request),
    )


@router.get("/model")
def model_card(request: Request) -> dict[str, Any]:
    card: dict[str, Any] = request.app.state.model_card
    return card


@router.post("/forecast/upload", response_model=ForecastRun, responses=ERRORS)
def forecast_upload(
    request: Request,
    file: Annotated[UploadFile, File(description="CSV with timestamp and weather columns")],
    battery: Annotated[str | None, Form(description="BatteryParams as JSON")] = None,
) -> ForecastRun:
    settings = _settings(request)
    content = file.file.read(settings.max_upload_bytes + 1)
    params = _parse_battery(battery)
    raw = read_csv(content, settings.max_upload_bytes)
    filename = Path(file.filename or "upload.csv").name[:200]
    run = _engine(request).run(raw, "upload", filename, _battery(params, settings).to_config())
    return _persist(request, run, content)


def _parse_battery(raw: str | None) -> BatteryParams | None:
    if not raw:
        return None
    try:
        return BatteryParams.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid battery parameters: {exc}") from exc


@router.post("/forecast/manual", response_model=ForecastRun, responses=ERRORS)
def forecast_manual(request: Request, body: ManualForecastRequest) -> ForecastRun:
    settings = _settings(request)
    if len(body.rows) > settings.max_manual_rows:
        raise HTTPException(
            status_code=422, detail=f"at most {settings.max_manual_rows} rows can be entered manually"
        )
    run = _engine(request).run(
        rows_frame(body.rows), "manual", None, _battery(body.battery, settings).to_config()
    )
    return _persist(request, run, None)


@router.post("/simulate", response_model=SimulateResponse, responses=ERRORS)
def simulate(request: Request, body: SimulateRequest) -> SimulateResponse:
    settings = _settings(request)
    battery = _battery(body.battery, settings).to_config()
    return _engine(request).simulate(body.rows, body.temperature_offset_c, battery)


@router.get("/runs", response_model=list[RunListItem], responses=ERRORS)
def list_runs(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[RunListItem]:
    return _store(request).list_runs(limit)


@router.get("/runs/{run_id}", response_model=ForecastRun, responses={404: {"model": ErrorOut}, **ERRORS})
def get_run(request: Request, run_id: str) -> ForecastRun:
    run = _store(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return run
