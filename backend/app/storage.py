"""Persistence of forecast runs.

`CatalystRunStore` is the deployed backend: raw uploads and full run documents
in Stratus, run summaries and per-hour signals in Data Store, read back with
ZCQL. `LocalRunStore` keeps the same contract on disk (SQLite + files) for
development and tests.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from app.schemas import ForecastRun, RunListItem

RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DATASTORE_BATCH = 200


class StorageError(RuntimeError):
    """Persistence backend failed; message is safe to show."""


class RunStore(Protocol):
    def save(self, run: ForecastRun, raw_upload: bytes | None) -> None: ...
    def list_runs(self, limit: int) -> list[RunListItem]: ...
    def get(self, run_id: str) -> ForecastRun | None: ...
    def check(self) -> None: ...


def list_item(run: ForecastRun) -> RunListItem:
    return RunListItem(
        id=run.id,
        created_at=run.created_at,
        source=run.source,
        filename=run.filename,
        rows=len(run.hours),
        window_start=run.summary.window_start,
        current_mode=run.summary.current_mode,
        peak_kw=run.summary.peak_kw,
        overload_hours=run.summary.overload_hours,
        transitions=run.summary.transitions,
    )


def valid_run_id(run_id: str) -> bool:
    return bool(RUN_ID_PATTERN.fullmatch(run_id))


class LocalRunStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._db = directory / "runs.sqlite3"
        (directory / "uploads").mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, item TEXT NOT NULL, document TEXT NOT NULL)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._db)
        except sqlite3.Error as exc:
            raise StorageError(f"local store unavailable: {exc}") from exc
        try:
            with connection:
                yield connection
        except sqlite3.Error as exc:
            raise StorageError(f"local store error: {exc}") from exc
        finally:
            connection.close()

    def save(self, run: ForecastRun, raw_upload: bytes | None) -> None:
        if raw_upload is not None:
            (self._dir / "uploads" / f"{run.id}.csv").write_bytes(raw_upload)
        with self._connect() as db:
            db.execute(
                "INSERT INTO runs (id, created_at, item, document) VALUES (?, ?, ?, ?)",
                (run.id, run.created_at.isoformat(), list_item(run).model_dump_json(), run.model_dump_json()),
            )

    def list_runs(self, limit: int) -> list[RunListItem]:
        with self._connect() as db:
            rows = db.execute("SELECT item FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [RunListItem.model_validate_json(item) for (item,) in rows]

    def get(self, run_id: str) -> ForecastRun | None:
        if not valid_run_id(run_id):
            return None
        with self._connect() as db:
            row = db.execute("SELECT document FROM runs WHERE id = ?", (run_id,)).fetchone()
        return (
            None
            if row is None
            else ForecastRun.model_validate_json(row[0]).model_copy(update={"persisted": True})
        )

    def check(self) -> None:
        with self._connect() as db:
            db.execute("SELECT 1 FROM runs LIMIT 1").fetchall()


class CatalystRunStore:
    """Catalyst Data Store + Stratus via zcatalyst_sdk.

    `app_factory` returns an initialised CatalystApp; in AppSail it is built
    from the incoming request's Catalyst headers, so it must be called on the
    thread that performs the SDK calls.
    """

    def __init__(
        self, app_factory: Callable[[], Any], bucket: str, runs_table: str, hours_table: str
    ) -> None:
        self._app_factory = app_factory
        self._bucket = bucket
        self._runs_table = runs_table
        self._hours_table = hours_table

    def save(self, run: ForecastRun, raw_upload: bytes | None) -> None:
        app = self._app()
        document_key = f"runs/{run.id}.json"
        upload_key = f"uploads/{run.id}.csv" if raw_upload is not None else ""
        try:
            bucket = app.stratus().bucket(self._bucket)
            if raw_upload is not None:
                bucket.put_object(upload_key, raw_upload)
            bucket.put_object(document_key, run.model_dump_json().encode())
            datastore = app.datastore()
            datastore.table(self._runs_table).insert_row(self._run_row(run, document_key, upload_key))
            hours = [self._hour_row(run.id, hour) for hour in run.model_dump(mode="json")["hours"]]
            table = datastore.table(self._hours_table)
            for start in range(0, len(hours), DATASTORE_BATCH):
                table.insert_rows(hours[start : start + DATASTORE_BATCH])
        except Exception as exc:
            raise StorageError(f"Catalyst storage failed: {exc}") from exc

    def list_runs(self, limit: int) -> list[RunListItem]:
        rows = self._query(f"SELECT * FROM {self._runs_table} ORDER BY CREATEDTIME DESC LIMIT {int(limit)}")
        return [RunListItem.model_validate_json(row["summary_json"]) for row in rows]

    def get(self, run_id: str) -> ForecastRun | None:
        if not valid_run_id(run_id):
            return None
        rows = self._query(f"SELECT document_key FROM {self._runs_table} WHERE run_id = '{run_id}'")
        if not rows:
            return None
        try:
            body = self._app().stratus().bucket(self._bucket).get_object(rows[0]["document_key"])
        except Exception as exc:
            raise StorageError(f"Catalyst storage failed: {exc}") from exc
        return ForecastRun.model_validate_json(body).model_copy(update={"persisted": True})

    def check(self) -> None:
        self._query(f"SELECT ROWID FROM {self._runs_table} LIMIT 1")

    def _app(self) -> Any:
        try:
            return self._app_factory()
        except Exception as exc:
            raise StorageError(f"Catalyst SDK not initialised: {exc}") from exc

    def _query(self, statement: str) -> list[Mapping[str, Any]]:
        try:
            result = self._app().zcql().execute_query(statement) or []
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"Catalyst Data Store query failed: {exc}") from exc
        return [entry[self._runs_table] for entry in result]

    @staticmethod
    def _run_row(run: ForecastRun, document_key: str, upload_key: str) -> dict[str, Any]:
        summary = run.summary
        return {
            "run_id": run.id,
            "source": run.source,
            "filename": run.filename or "",
            "row_count": len(run.hours),
            "window_start": summary.window_start.isoformat(),
            "peak_kw": round(summary.peak_kw, 3),
            "overload_hours": summary.overload_hours,
            "transitions": summary.transitions,
            "current_mode": str(summary.current_mode),
            "rows_rejected": run.quality.rows_rejected,
            "rows_imputed": run.quality.rows_imputed,
            "document_key": document_key,
            "upload_key": upload_key,
            "summary_json": list_item(run).model_dump_json(),
        }

    @staticmethod
    def _hour_row(run_id: str, hour: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "hour_ts": hour["timestamp"],
            "ambient_temp_c": hour["ambient_temp_c"],
            "humidity_pct": hour["humidity_pct"],
            "solar_irradiance_wm2": hour["solar_irradiance_wm2"],
            "predicted_kw": round(hour["predicted_kw"], 3),
            "grid_mode": hour["mode"],
            "overload": hour["overload"],
            "soc_pct": round(hour["soc_pct"], 3),
            "reasons": json.dumps(hour["reasons"]),
        }
