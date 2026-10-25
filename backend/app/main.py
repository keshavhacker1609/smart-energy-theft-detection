"""Application factory and error mapping. AppSail entry point: app.main:app."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import ServiceUnavailableError, router
from app.cleaning import IngestError
from app.config import Settings, get_settings
from app.forecast import Predictor, quality_issue
from app.quickml_client import QuickMLClient, QuickMLError, QuickMLSettings
from app.schemas import ErrorOut, ModelInfo
from app.storage import CatalystRunStore, LocalRunStore, RunStore, StorageError

log = logging.getLogger("gridcast")
MODEL_CARD_PATH = Path(__file__).with_name("model_card.json")
StoreFactory = Callable[[Request], RunStore]


def load_model_card(path: Path = MODEL_CARD_PATH) -> dict[str, Any]:
    card: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return card


def default_predictor() -> tuple[Predictor | None, str | None]:
    try:
        return QuickMLClient(QuickMLSettings.from_env()), None
    except QuickMLError as exc:
        log.warning("QuickML client not configured: %s", exc)
        return None, str(exc)


class _HeaderCarrier:
    """Minimal request object accepted by zcatalyst_sdk.initialize(req=...)."""

    def __init__(self, headers: Mapping[str, str]) -> None:
        self.headers = dict(headers)


def default_store_factory(settings: Settings) -> StoreFactory:
    if settings.storage_backend == "local":
        store = LocalRunStore(settings.local_data_dir)
        return lambda _request: store

    def factory(request: Request) -> RunStore:
        import zcatalyst_sdk

        headers = dict(request.headers)
        return CatalystRunStore(
            app_factory=lambda: zcatalyst_sdk.initialize(req=_HeaderCarrier(headers)),
            bucket=settings.stratus_bucket,
            runs_table=settings.datastore_runs_table,
            hours_table=settings.datastore_hours_table,
        )

    return factory


def _error(status: int, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorOut(detail=detail, **extra).model_dump())


def create_app(
    settings: Settings | None = None,
    predictor: Predictor | None = None,
    store_factory: StoreFactory | None = None,
    model_card: dict[str, Any] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    card = model_card if model_card is not None else load_model_card()

    app = FastAPI(
        title="GridCast API",
        version="1.0.0",
        description="Microgrid demand forecasting, grid-transition signals and battery dispatch.",
    )
    app.state.settings = settings
    app.state.model_card = card
    app.state.model_info = ModelInfo(name=card["selected"], validation_rmse_kw=card["validation_rmse_kw"])
    if predictor is None:
        app.state.predictor, app.state.predictor_error = default_predictor()
    else:
        app.state.predictor, app.state.predictor_error = predictor, None
    app.state.store_factory = store_factory or default_store_factory(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(IngestError)
    def _ingest(_: Request, exc: IngestError) -> JSONResponse:
        return _error(422, str(exc), issues=[quality_issue(i) for i in exc.issues])

    @app.exception_handler(QuickMLError)
    def _quickml(_: Request, exc: QuickMLError) -> JSONResponse:
        log.error("QuickML failure: %s", exc)
        return _error(502, f"Forecast model endpoint failed: {exc}", retryable=True)

    @app.exception_handler(ServiceUnavailableError)
    def _unavailable(_: Request, exc: ServiceUnavailableError) -> JSONResponse:
        return _error(503, exc.detail, retryable=exc.retryable)

    @app.exception_handler(StorageError)
    def _storage(_: Request, exc: StorageError) -> JSONResponse:
        log.error("storage failure: %s", exc)
        return _error(503, str(exc), retryable=True)

    @app.exception_handler(RequestValidationError)
    def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        messages = []
        for error in exc.errors()[:10]:
            location = ".".join(str(part) for part in error["loc"] if part != "body")
            messages.append(f"{location}: {error['msg']}" if location else str(error["msg"]))
        return _error(422, "; ".join(messages) or "invalid request")

    @app.exception_handler(StarletteHTTPException)
    def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, str(exc.detail))

    @app.exception_handler(Exception)
    def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _error(500, "Unexpected server error; the request was not completed", retryable=True)

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = create_app()
