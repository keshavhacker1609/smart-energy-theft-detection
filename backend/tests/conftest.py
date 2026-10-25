from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import LinearRegression

from app.config import Settings
from app.features import TARGET, feature_names
from app.main import create_app, load_model_card
from app.storage import LocalRunStore, RunStore

REPO = Path(__file__).resolve().parents[2]


class ReferencePredictor:
    """The selected model fitted locally, standing in for the QuickML endpoint."""

    def __init__(self) -> None:
        table = pd.read_csv(REPO / "ml" / "quickml_train.csv")
        self._model = LinearRegression().fit(table[feature_names()], table[TARGET])
        self.calls = 0

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        self.calls += 1
        return np.asarray(self._model.predict(features[feature_names()]), dtype=float)


@pytest.fixture(scope="session")
def reference_predictor() -> ReferencePredictor:
    return ReferencePredictor()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(local_data_dir=tmp_path / "data", health_cache_s=0)


@pytest.fixture
def make_client(settings: Settings) -> Iterator[Callable[..., TestClient]]:
    def factory(predictor: Any = None, store: RunStore | None = None, **overrides: Any) -> TestClient:
        app_settings = settings.model_copy(update=overrides)
        run_store = store or LocalRunStore(app_settings.local_data_dir)
        app = create_app(
            settings=app_settings,
            predictor=predictor,
            store_factory=lambda _request: run_store,
            model_card=load_model_card(),
        )
        if predictor is None:
            app.state.predictor, app.state.predictor_error = None, "QUICKML_ENDPOINT_URL is not set"
        return TestClient(app, raise_server_exceptions=False)

    yield factory


@pytest.fixture
def client(make_client: Callable[..., TestClient], reference_predictor: ReferencePredictor) -> TestClient:
    return make_client(reference_predictor)
