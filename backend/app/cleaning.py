"""Telemetry ingestion: schema normalisation, validation, repair and a data-quality report.

Rows are never silently changed. Every repair, imputation or rejection is
recorded as an Issue so the UI can show exactly what was done and why.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from app.features import HUMIDITY, IRRADIANCE, TARGET, TEMPERATURE, TIMESTAMP, WEATHER_COLUMNS

ACTUAL = "actual_kw"
SOURCE_ROW = "source_row"
IMPUTED = "imputed"
MAX_REPORTED_ISSUES = 200

COLUMN_ALIASES: Mapping[str, str] = {
    **dict.fromkeys(("timestamp", "time", "datetime", "date_time", "ts", "hour_start"), TIMESTAMP),
    **dict.fromkeys(
        (
            "ambient_temp_c",
            "ambient_temp",
            "temp",
            "temp_c",
            "temperature",
            "temperature_c",
            "ambient_temperature",
        ),
        TEMPERATURE,
    ),
    **dict.fromkeys(("humidity_pct", "humidity", "relative_humidity", "rh", "humidity_percent"), HUMIDITY),
    **dict.fromkeys(
        (
            "solar_irradiance_wm2",
            "solar_irradiance",
            "irradiance",
            "solar",
            "ghi",
            "irradiance_wm2",
            "solar_irradiance_w_m2",
            "irradiance_w_m2",
        ),
        IRRADIANCE,
    ),
    **dict.fromkeys((TARGET, "actual_demand_kw", "demand_kw", "demand", "load_kw"), ACTUAL),
}
REQUIRED: tuple[str, ...] = (TIMESTAMP, *WEATHER_COLUMNS)


class IngestError(ValueError):
    """Input cannot be forecast; message is safe to show to the user."""

    def __init__(self, message: str, issues: Sequence[Issue] = ()) -> None:
        super().__init__(message)
        self.issues = list(issues)


@dataclass(frozen=True)
class CleaningLimits:
    max_rows: int = 5000
    max_impute_gap_hours: int = 3
    temp_min_c: float = -30.0
    temp_max_c: float = 55.0
    humidity_clip_tolerance_pct: float = 5.0
    irradiance_max_wm2: float = 1500.0
    irradiance_clip_tolerance_wm2: float = 10.0


DEFAULT_LIMITS = CleaningLimits()


@dataclass(frozen=True)
class Issue:
    row: int | None
    column: str | None
    kind: str
    detail: str
    action: str


@dataclass(frozen=True)
class Gap:
    after: pd.Timestamp
    before: pd.Timestamp
    missing_hours: int


@dataclass
class QualityReport:
    rows_received: int = 0
    rows_accepted: int = 0
    rows_imputed: int = 0
    rows_rejected: int = 0
    values_imputed: int = 0
    values_clipped: int = 0
    duplicates_removed: int = 0
    columns_renamed: dict[str, str] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    issues_truncated: int = 0

    def add(self, issue: Issue) -> None:
        if len(self.issues) < MAX_REPORTED_ISSUES:
            self.issues.append(issue)
        else:
            self.issues_truncated += 1


@dataclass(frozen=True)
class CleanResult:
    """Accepted rows sorted by time, with source row numbers and imputed column names."""

    frame: pd.DataFrame
    report: QualityReport


def read_csv(content: bytes, max_bytes: int) -> pd.DataFrame:
    if not content.strip():
        raise IngestError("the file is empty")
    if len(content) > max_bytes:
        raise IngestError(f"file is {len(content):,} bytes; the limit is {max_bytes:,}")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    try:
        frame = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, skipinitialspace=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise IngestError(f"could not parse CSV: {exc}") from exc
    return frame.dropna(how="all")


def normalize_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Map header variants to canonical names; unknown columns are dropped."""
    mapping: dict[str, str] = {}
    for original in frame.columns:
        key = re.sub(r"[^a-z0-9]+", "_", str(original).strip().lower()).strip("_")
        canonical = COLUMN_ALIASES.get(key)
        if canonical is None:
            continue
        if canonical in mapping.values():
            other = next(k for k, v in mapping.items() if v == canonical)
            raise IngestError(f"columns '{other}' and '{original}' both map to '{canonical}'")
        mapping[str(original)] = canonical

    missing = [c for c in REQUIRED if c not in mapping.values()]
    if missing:
        found = ", ".join(f"'{c}'" for c in frame.columns) or "none"
        raise IngestError(f"missing required column(s): {', '.join(missing)} (found: {found})")

    renamed = {k: v for k, v in mapping.items() if k != v}
    return frame[list(mapping)].rename(columns=mapping), renamed


def _parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = pd.Timestamp(text)
    except (ValueError, TypeError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.tz_localize(None) if parsed.tzinfo is not None else parsed


def clean(raw: pd.DataFrame, limits: CleaningLimits = DEFAULT_LIMITS) -> CleanResult:
    report = QualityReport(rows_received=len(raw))
    if raw.empty:
        raise IngestError("no data rows")
    if len(raw) > limits.max_rows:
        raise IngestError(f"{len(raw):,} rows received; the limit is {limits.max_rows:,}")

    frame, report.columns_renamed = normalize_columns(raw)
    frame = frame.reset_index(drop=True)
    frame[SOURCE_ROW] = np.arange(1, len(frame) + 1)

    frame = _clean_timestamps(frame, report)
    for column in WEATHER_COLUMNS:
        frame[column] = _to_numeric(frame, column, report)
    _apply_ranges(frame, limits, report)
    frame[ACTUAL] = _optional_actual(frame)

    frame = _impute(frame, limits, report)
    if frame.empty:
        raise IngestError("no usable rows after cleaning", report.issues)

    report.rows_accepted = len(frame)
    report.rows_rejected = report.rows_received - report.rows_accepted
    report.rows_imputed = int(sum(bool(cols) for cols in frame[IMPUTED]))
    report.gaps = _find_gaps(frame[TIMESTAMP])
    columns = [TIMESTAMP, *WEATHER_COLUMNS, ACTUAL, SOURCE_ROW, IMPUTED]
    return CleanResult(frame=frame[columns].reset_index(drop=True), report=report)


def _clean_timestamps(frame: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    parsed = [_parse_timestamp(v) for v in frame[TIMESTAMP]]
    valid = []
    for row, raw_value, ts in zip(frame[SOURCE_ROW], frame[TIMESTAMP], parsed, strict=True):
        if ts is None:
            report.add(
                Issue(int(row), TIMESTAMP, "invalid_timestamp", f"cannot parse {raw_value!r}", "row rejected")
            )
            valid.append(False)
            continue
        valid.append(True)
        if ts != ts.floor("h"):
            report.add(
                Issue(
                    int(row),
                    TIMESTAMP,
                    "unaligned_timestamp",
                    f"{ts} is not on the hour",
                    f"aligned to {ts.floor('h')}",
                )
            )
    frame = frame.loc[valid].copy()
    frame[TIMESTAMP] = pd.to_datetime(pd.Series([ts for ts in parsed if ts is not None], index=frame.index))
    frame[TIMESTAMP] = frame[TIMESTAMP].dt.floor("h")

    frame = frame.sort_values([TIMESTAMP, SOURCE_ROW], kind="stable")
    duplicated = frame[TIMESTAMP].duplicated(keep="first")
    for row, ts in zip(frame.loc[duplicated, SOURCE_ROW], frame.loc[duplicated, TIMESTAMP], strict=True):
        report.add(
            Issue(
                int(row),
                TIMESTAMP,
                "duplicate_timestamp",
                f"{ts} already present",
                "row dropped, first occurrence kept",
            )
        )
    report.duplicates_removed = int(duplicated.sum())
    return frame.loc[~duplicated].reset_index(drop=True)


def _to_numeric(frame: pd.DataFrame, column: str, report: QualityReport) -> pd.Series:
    raw = frame[column]
    numeric = pd.to_numeric(raw, errors="coerce").astype(float)
    blank = raw.isna() | raw.astype(str).str.strip().str.lower().isin(
        ["", "nan", "null", "none", "na", "n/a"]
    )
    for row, value in zip(
        frame.loc[numeric.isna() & ~blank, SOURCE_ROW], raw[numeric.isna() & ~blank], strict=True
    ):
        report.add(
            Issue(int(row), column, "non_numeric", f"value {value!r} is not a number", "treated as missing")
        )
    numeric[~np.isfinite(numeric)] = np.nan
    return numeric


def _apply_ranges(frame: pd.DataFrame, limits: CleaningLimits, report: QualityReport) -> None:
    def invalidate(mask: pd.Series, column: str, rule: str) -> None:
        for row, value in zip(frame.loc[mask, SOURCE_ROW], frame.loc[mask, column], strict=True):
            report.add(
                Issue(int(row), column, "out_of_range", f"{value:g} outside {rule}", "treated as missing")
            )
        frame.loc[mask, column] = np.nan

    def clip(mask: pd.Series, column: str, bound: float) -> None:
        for row, value in zip(frame.loc[mask, SOURCE_ROW], frame.loc[mask, column], strict=True):
            report.add(
                Issue(
                    int(row), column, "clipped", f"{value:g} slightly outside range", f"clipped to {bound:g}"
                )
            )
        frame.loc[mask, column] = bound
        report.values_clipped += int(mask.sum())

    temp = frame[TEMPERATURE]
    invalidate(
        (temp < limits.temp_min_c) | (temp > limits.temp_max_c),
        TEMPERATURE,
        f"{limits.temp_min_c:g} to {limits.temp_max_c:g} C",
    )

    hum, tol = frame[HUMIDITY], limits.humidity_clip_tolerance_pct
    invalidate((hum < -tol) | (hum > 100 + tol), HUMIDITY, "0 to 100 %")
    hum = frame[HUMIDITY]
    clip(hum < 0, HUMIDITY, 0.0)
    clip(frame[HUMIDITY] > 100, HUMIDITY, 100.0)

    irr, tol, top = frame[IRRADIANCE], limits.irradiance_clip_tolerance_wm2, limits.irradiance_max_wm2
    invalidate((irr < -tol) | (irr > top + tol), IRRADIANCE, f"0 to {top:g} W/m2")
    clip(frame[IRRADIANCE] < 0, IRRADIANCE, 0.0)
    clip(frame[IRRADIANCE] > top, IRRADIANCE, top)


def _optional_actual(frame: pd.DataFrame) -> pd.Series:
    if ACTUAL not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    actual = pd.to_numeric(frame[ACTUAL], errors="coerce").astype(float)
    actual[~np.isfinite(actual)] = np.nan
    return actual


def _impute(frame: pd.DataFrame, limits: CleaningLimits, report: QualityReport) -> pd.DataFrame:
    """Time-interpolate short gaps; reject rows whose gap exceeds the limit."""
    imputed: list[list[str]] = [[] for _ in range(len(frame))]
    reject = np.zeros(len(frame), dtype=bool)
    hours = (
        ((frame[TIMESTAMP] - frame[TIMESTAMP].iloc[0]) / pd.Timedelta(hours=1)).to_numpy(float)
        if len(frame)
        else []
    )

    for column in WEATHER_COLUMNS:
        values = frame[column].to_numpy(float, copy=True)
        missing = np.isnan(values)
        if not missing.any():
            continue
        if missing.all():
            for row in frame[SOURCE_ROW]:
                report.add(
                    Issue(int(row), column, "gap_too_large", "no valid values in the column", "row rejected")
                )
            reject[:] = True
            continue
        valid_idx = np.flatnonzero(~missing)
        filled = np.interp(hours, np.asarray(hours)[valid_idx], values[valid_idx])
        for start, stop in _runs(missing):
            before = valid_idx[valid_idx < start]
            after = valid_idx[valid_idx >= stop]
            left = hours[before[-1]] if len(before) else None
            right = hours[after[0]] if len(after) else None
            if left is not None and right is not None:
                span = right - left - 1
            else:
                anchor = left if left is not None else right
                span = max(abs(hours[i] - anchor) for i in range(start, stop))
            if span <= limits.max_impute_gap_hours:
                for i in range(start, stop):
                    values[i] = filled[i]
                    imputed[i].append(column)
                    report.add(
                        Issue(
                            int(frame[SOURCE_ROW].iloc[i]),
                            column,
                            "imputed",
                            "missing value filled by time interpolation",
                            f"set to {filled[i]:.2f}",
                        )
                    )
                report.values_imputed += stop - start
            else:
                for i in range(start, stop):
                    reject[i] = True
                    report.add(
                        Issue(
                            int(frame[SOURCE_ROW].iloc[i]),
                            column,
                            "gap_too_large",
                            f"{span:g} h gap exceeds {limits.max_impute_gap_hours} h limit",
                            "row rejected",
                        )
                    )
        frame[column] = values

    frame[IMPUTED] = [tuple(cols) for cols in imputed]
    return frame.loc[~reject].reset_index(drop=True)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [start, stop) index ranges where mask is True."""
    padded = np.concatenate(([False], mask, [False])).astype(int)
    edges = np.flatnonzero(np.diff(padded))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True))


def _find_gaps(timestamps: pd.Series) -> list[Gap]:
    gaps: list[Gap] = []
    values = timestamps.tolist()
    for previous, current in pairwise(values):
        missing = int((current - previous) / pd.Timedelta(hours=1)) - 1
        if missing > 0:
            gaps.append(Gap(after=previous, before=current, missing_hours=missing))
    return gaps
