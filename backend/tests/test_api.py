import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.quickml_client import QuickMLError
from app.schemas import ForecastRun, RunListItem
from app.storage import StorageError

REPO = Path(__file__).resolve().parents[2]
SAMPLE = (REPO / "sample_test_input.csv").read_bytes()


def _rows(n: int = 24, start: str = "2015-07-01 00:00:00", temp: float = 30.0) -> list[dict[str, Any]]:
    stamps = pd.date_range(start, periods=n, freq="h")
    return [
        {
            "timestamp": f"{ts:%Y-%m-%d %H:%M:%S}",
            "ambient_temp_c": temp,
            "humidity_pct": 55.0,
            "solar_irradiance_wm2": 200.0 if 7 <= ts.hour <= 17 else 0.0,
        }
        for ts in stamps
    ]


def _upload(client: TestClient, content: bytes = SAMPLE, name: str = "sample.csv", **data: str) -> Any:
    return client.post("/api/forecast/upload", files={"file": (name, content, "text/csv")}, data=data)


class FailingPredictor:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        raise QuickMLError("endpoint unavailable after 4 attempts (Timeout)")


class BrokenStore:
    def save(self, run: ForecastRun, raw_upload: bytes | None) -> None:
        raise StorageError("Catalyst storage failed: bucket missing")

    def list_runs(self, limit: int) -> list[RunListItem]:
        raise StorageError("Catalyst Data Store query failed: table missing")

    def get(self, run_id: str) -> ForecastRun | None:
        raise StorageError("Catalyst Data Store query failed: table missing")

    def check(self) -> None:
        raise StorageError("Catalyst Data Store query failed: table missing")


def test_upload_sample_runs_full_pipeline(client: TestClient) -> None:
    response = _upload(client)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["persisted"] is True and run["source"] == "upload" and run["filename"] == "sample.csv"
    assert len(run["hours"]) == 1000
    summary = run["summary"]
    assert summary["window_hours"] == 24
    assert summary["window_start"] == "2015-06-16T15:00:00"
    assert summary["storage_hours"] + summary["grid_hours"] == 24
    assert run["quality"]["rows_accepted"] == 1000
    assert run["model"]["validation_rmse_kw"] > 0
    assert any(e["kind"] == "mode" for e in run["events"])


def test_every_hour_obeys_controller_spec(client: TestClient) -> None:
    for hour in _upload(client).json()["hours"]:
        h = int(hour["timestamp"][11:13])
        expected = "RENEWABLE_STORAGE" if hour["predicted_kw"] > 160 or 18 <= h <= 22 else "MAIN_GRID"
        assert hour["mode"] == expected
        assert hour["overload"] is (hour["predicted_kw"] >= 200)


def test_runs_are_listed_and_reloaded(client: TestClient) -> None:
    first = _upload(client).json()
    second = client.post("/api/forecast/manual", json={"rows": _rows(6)}).json()
    listing = client.get("/api/runs").json()
    assert [item["id"] for item in listing] == [second["id"], first["id"]]
    reloaded = client.get(f"/api/runs/{first['id']}").json()
    assert reloaded["hours"] == first["hours"] and reloaded["summary"] == first["summary"]


def test_unknown_or_malformed_run_id_is_404(client: TestClient) -> None:
    assert client.get(f"/api/runs/{'0' * 32}").status_code == 404
    response = client.get("/api/runs/' OR 1=1 --")
    assert response.status_code == 404 and response.json()["detail"].startswith("run ")


def test_manual_rows_with_gaps_are_repaired_and_reported(client: TestClient) -> None:
    rows = _rows(6)
    rows[2]["humidity_pct"] = None
    rows[4]["ambient_temp_c"] = 999
    run = client.post("/api/forecast/manual", json={"rows": rows}).json()
    quality = run["quality"]
    assert quality["rows_imputed"] == 2 and quality["rows_rejected"] == 0
    assert {i["kind"] for i in quality["issues"]} == {"imputed", "out_of_range"}
    assert any(e["phase"] == "ingest" and e["kind"] == "imputed" for e in run["events"])


def test_manual_row_limit(client: TestClient) -> None:
    response = client.post("/api/forecast/manual", json={"rows": _rows(25)})
    assert response.status_code == 422 and "at most 24 rows" in response.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"rows": []}, "rows"),
        ({"rows": [{"timestamp": "", "ambient_temp_c": 1}]}, "timestamp"),
        ({"rows": _rows(2), "battery": {"capacity_kwh": -5}}, "battery"),
    ],
)
def test_request_validation_errors_are_readable(
    client: TestClient, payload: dict[str, Any], fragment: str
) -> None:
    response = client.post("/api/forecast/manual", json=payload)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


def test_missing_columns_return_actionable_422(client: TestClient) -> None:
    response = _upload(client, b"timestamp,temp\n2015-07-01 00:00,20\n")
    assert response.status_code == 422
    assert "missing required column(s): humidity_pct, solar_irradiance_wm2" in response.json()["detail"]


def test_unusable_rows_return_issues(client: TestClient) -> None:
    body = b"timestamp,temp,humidity,irradiance\nnot-a-date,20,50,0\n"
    response = _upload(client, body)
    assert response.status_code == 422
    assert response.json()["issues"][0]["kind"] == "invalid_timestamp"


def test_oversized_upload_is_rejected(
    make_client: Callable[..., TestClient], reference_predictor: Any
) -> None:
    client = make_client(reference_predictor, max_upload_bytes=1000)
    response = _upload(client)
    assert response.status_code == 422 and "limit is 1,000" in response.json()["detail"]


def test_custom_battery_parameters_are_applied(client: TestClient) -> None:
    battery = {
        "capacity_kwh": 50,
        "initial_soc_pct": 100,
        "reserve_soc_pct": 10,
        "max_charge_kw": 10,
        "max_discharge_kw": 50,
        "round_trip_efficiency": 1.0,
        "solar_reference_wm2": 500,
    }
    run = _upload(client, battery=json.dumps(battery)).json()
    assert run["battery"]["capacity_kwh"] == 50
    assert run["summary"]["reserve_low_hours"] > 0
    assert any(e["kind"] == "battery_reserve_low" for e in run["events"])


def test_invalid_battery_form_field(client: TestClient) -> None:
    response = _upload(client, battery="{not json")
    assert response.status_code == 422 and "invalid battery parameters" in response.json()["detail"]


def test_actuals_in_upload_are_scored(client: TestClient) -> None:
    train = (REPO / "ml" / "data" / "train_telemetry.csv").read_text().splitlines()
    content = "\n".join([train[0], *train[-48:]]).encode()
    summary = _upload(client, content).json()["summary"]
    assert summary["actual_rows"] == 48
    assert 0 < summary["actual_rmse_kw"] < 20


def test_simulate_returns_baseline_scenario_and_delta(client: TestClient, reference_predictor: Any) -> None:
    calls_before = reference_predictor.calls
    body = {"rows": _rows(24, temp=26.0), "temperature_offset_c": 8.0}
    result = client.post("/api/simulate", json=body).json()
    assert reference_predictor.calls == calls_before + 1
    assert result["scenario"]["summary"]["peak_kw"] > result["baseline"]["summary"]["peak_kw"]
    assert result["delta"]["overload_hours"] >= 0
    assert result["delta"]["peak_kw"] == pytest.approx(8.0 * 8.6, rel=0.05)
    assert client.get("/api/runs").json() == []


def test_simulate_offset_is_bounded(client: TestClient) -> None:
    response = client.post("/api/simulate", json={"rows": _rows(2), "temperature_offset_c": 11})
    assert response.status_code == 422


def test_quickml_failure_is_502_and_retryable(make_client: Callable[..., TestClient]) -> None:
    response = _upload(make_client(FailingPredictor()))
    assert response.status_code == 502
    assert response.json()["retryable"] is True
    assert "Forecast model endpoint failed" in response.json()["detail"]


def test_unconfigured_quickml_is_503(make_client: Callable[..., TestClient]) -> None:
    response = _upload(make_client(None))
    assert response.status_code == 503
    assert "QUICKML_ENDPOINT_URL" in response.json()["detail"]


def test_storage_outage_still_returns_forecast(
    make_client: Callable[..., TestClient], reference_predictor: Any
) -> None:
    client = make_client(reference_predictor, store=BrokenStore())
    run = _upload(client).json()
    assert run["persisted"] is False and "bucket missing" in run["storage_warning"]
    listing = client.get("/api/runs")
    assert listing.status_code == 503 and listing.json()["retryable"] is True


def test_health_reports_each_dependency(
    make_client: Callable[..., TestClient], reference_predictor: Any
) -> None:
    healthy = make_client(reference_predictor).get("/api/health").json()
    assert healthy["status"] == "ok" and healthy["quickml"]["latency_ms"] is not None
    degraded = make_client(FailingPredictor(), store=BrokenStore()).get("/api/health").json()
    assert degraded["status"] == "degraded"
    assert not degraded["quickml"]["ok"] and not degraded["storage"]["ok"]


def test_config_exposes_thresholds(client: TestClient) -> None:
    config = client.get("/api/config").json()
    assert (config["storage_threshold_kw"], config["overload_threshold_kw"]) == (160, 200)
    assert (config["peak_start_hour"], config["peak_end_hour"]) == (18, 22)
    assert config["temperature_offset_range_c"] == [-10, 10]


def test_model_card_is_served(client: TestClient) -> None:
    card = client.get("/api/model").json()
    assert card["selected"] == "linear_hour_cdd_hdd"
    assert len(card["hourly_profile"]) == 24 and card["holdout_series"]


def test_openapi_docs_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/forecast/upload",
        "/api/forecast/manual",
        "/api/simulate",
        "/api/runs",
        "/api/health",
    } <= set(paths)
