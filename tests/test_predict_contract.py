"""End-to-end check of the predict.py contract against the local reference endpoint."""

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import predict
from local_endpoint import fit_reference_model, make_handler

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def endpoint_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fit_reference_model()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/predict"
    server.shutdown()


@pytest.fixture
def configured(endpoint_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUICKML_ENDPOINT_URL", endpoint_url)
    monkeypatch.setenv("QUICKML_BATCH_SIZE", "64")


@pytest.mark.usefixtures("configured")
def test_one_finite_prediction_per_row_in_order() -> None:
    df = pd.read_csv(REPO / "sample_test_input.csv")
    forward = predict.predict(df)
    reverse = predict.predict(df.iloc[::-1].reset_index(drop=True))
    assert forward.shape == (len(df),)
    assert np.isfinite(forward).all()
    np.testing.assert_allclose(reverse, forward[::-1])


@pytest.mark.usefixtures("configured")
def test_cli_writes_timestamp_and_prediction(tmp_path: Path) -> None:
    output = tmp_path / "predictions.csv"
    predict.main(["--input", str(REPO / "sample_test_input.csv"), "--output", str(output)])
    written = pd.read_csv(output)
    source = pd.read_csv(REPO / "sample_test_input.csv")
    assert list(written.columns) == ["timestamp", "target_demand_kw"]
    assert written["timestamp"].tolist() == source["timestamp"].tolist()


def test_fails_loudly_without_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("QUICKML_ENDPOINT_URL", raising=False)
    monkeypatch.setattr(predict, "ROOT", tmp_path)
    with pytest.raises(Exception, match="QUICKML_ENDPOINT_URL"):
        predict.predict(pd.read_csv(REPO / "sample_test_input.csv").head(2))
