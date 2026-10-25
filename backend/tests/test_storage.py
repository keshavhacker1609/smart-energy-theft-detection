from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.battery import BatteryConfig
from app.cleaning import DEFAULT_LIMITS
from app.controller import ControllerRules
from app.forecast import ForecastEngine
from app.schemas import ForecastRun, ModelInfo
from app.storage import DATASTORE_BATCH, CatalystRunStore, LocalRunStore, StorageError, list_item


class ConstantPredictor:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return np.full(len(features), 180.0)


def _run(n: int = 30) -> ForecastRun:
    stamps = pd.date_range("2015-07-01", periods=n, freq="h").astype(str)
    raw = pd.DataFrame(
        {"timestamp": stamps, "ambient_temp_c": 30.0, "humidity_pct": 50.0, "solar_irradiance_wm2": 0.0}
    )
    engine = ForecastEngine(
        ConstantPredictor(),
        ControllerRules(),
        DEFAULT_LIMITS,
        24,
        ModelInfo(name="m", validation_rmse_kw=8.7),
    )
    return engine.run(raw, "upload", "x.csv", BatteryConfig())


def test_local_store_round_trip(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)
    run = _run()
    store.save(run, b"raw,csv\n")
    assert (tmp_path / "uploads" / f"{run.id}.csv").read_bytes() == b"raw,csv\n"
    assert store.list_runs(10) == [list_item(run)]
    loaded = store.get(run.id)
    assert loaded is not None and loaded.persisted
    assert loaded.model_dump(exclude={"persisted"}) == run.model_dump(exclude={"persisted"})
    assert store.get("f" * 32) is None and store.get("../etc") is None
    store.check()


def test_local_store_lists_newest_first(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)
    older = _run().model_copy(update={"created_at": datetime(2026, 1, 1, tzinfo=UTC)})
    newer = _run().model_copy(update={"created_at": datetime(2026, 2, 1, tzinfo=UTC)})
    store.save(older, None)
    store.save(newer, None)
    assert [r.id for r in store.list_runs(1)] == [newer.id]


def test_local_store_reports_sqlite_errors(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)
    run = _run()
    store.save(run, None)
    with pytest.raises(StorageError, match="local store error"):
        store.save(run, None)


class FakeTable:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.batches: list[int] = []

    def insert_row(self, row: dict[str, Any]) -> dict[str, Any]:
        self.rows.append(row)
        return row

    def insert_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.batches.append(len(rows))
        self.rows.extend(rows)
        return rows


class FakeCatalyst:
    """Implements the slice of the zcatalyst_sdk surface the store uses."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.tables: dict[str, FakeTable] = {"Runs": FakeTable(), "Hours": FakeTable()}
        self.queries: list[str] = []

    def stratus(self) -> "FakeCatalyst":
        return self

    def bucket(self, name: str) -> "FakeCatalyst":
        assert name == "bucket"
        return self

    def put_object(self, key: str, body: bytes) -> bool:
        self.objects[key] = body
        return True

    def get_object(self, key: str) -> bytes:
        return self.objects[key]

    def datastore(self) -> "FakeCatalyst":
        return self

    def table(self, name: str) -> FakeTable:
        return self.tables[name]

    def zcql(self) -> "FakeCatalyst":
        return self

    def execute_query(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        rows = list(reversed(self.tables["Runs"].rows))
        if "WHERE run_id" in query:
            run_id = query.split("'")[1]
            rows = [r for r in rows if r["run_id"] == run_id]
        return [{"Runs": r} for r in rows]


def _catalyst_store(fake: FakeCatalyst) -> CatalystRunStore:
    return CatalystRunStore(lambda: fake, bucket="bucket", runs_table="Runs", hours_table="Hours")


def test_catalyst_store_writes_stratus_and_datastore() -> None:
    fake = FakeCatalyst()
    store = _catalyst_store(fake)
    run = _run(450)
    store.save(run, b"raw")
    assert fake.objects[f"uploads/{run.id}.csv"] == b"raw"
    assert f"runs/{run.id}.json" in fake.objects
    (row,) = fake.tables["Runs"].rows
    assert row["run_id"] == run.id and row["row_count"] == 450
    assert fake.tables["Hours"].batches == [DATASTORE_BATCH, DATASTORE_BATCH, 50]
    hour = fake.tables["Hours"].rows[0]
    assert hour["grid_mode"] == "RENEWABLE_STORAGE" and hour["hour_ts"] == "2015-07-01T00:00:00"


def test_catalyst_store_reads_back() -> None:
    fake = FakeCatalyst()
    store = _catalyst_store(fake)
    run = _run()
    store.save(run, None)
    assert f"uploads/{run.id}.csv" not in fake.objects
    assert store.list_runs(5) == [list_item(run)]
    assert "LIMIT 5" in fake.queries[-1]
    loaded = store.get(run.id)
    assert loaded is not None and loaded.persisted and loaded.id == run.id
    assert store.get("0" * 32) is None
    assert store.get("x' OR '1'='1") is None
    store.check()


def test_catalyst_failures_become_storage_errors() -> None:
    def broken() -> Any:
        raise RuntimeError("Catalyst headers are empty")

    store = CatalystRunStore(broken, bucket="bucket", runs_table="Runs", hours_table="Hours")
    with pytest.raises(StorageError, match="not initialised"):
        store.check()
    with pytest.raises(StorageError, match="not initialised"):
        store.save(_run(), None)


def test_catalyst_sdk_errors_become_storage_errors() -> None:
    fake = FakeCatalyst()
    fake.tables.clear()
    store = _catalyst_store(fake)
    with pytest.raises(StorageError, match="Catalyst storage failed"):
        store.save(_run(), None)
