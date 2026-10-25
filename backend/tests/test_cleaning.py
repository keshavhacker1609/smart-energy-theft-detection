from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.cleaning import (
    ACTUAL,
    IMPUTED,
    SOURCE_ROW,
    CleaningLimits,
    CleanResult,
    IngestError,
    clean,
    read_csv,
)

REPO = Path(__file__).resolve().parents[2]


def _frame(n: int = 6, start: str = "2015-07-01 00:00:00") -> pd.DataFrame:
    stamps = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame(
        {
            "timestamp": stamps.strftime("%Y-%m-%d %H:%M:%S"),
            "ambient_temp_c": np.linspace(20, 25, n),
            "humidity_pct": [50.0] * n,
            "solar_irradiance_wm2": [0.0] * n,
        }
    )


def _append(frame: pd.DataFrame, timestamp: str, temp: float | None) -> pd.DataFrame:
    row = {"timestamp": timestamp, "ambient_temp_c": temp, "humidity_pct": 50.0, "solar_irradiance_wm2": 0.0}
    return pd.concat([frame, pd.DataFrame([row])], ignore_index=True)


def _kinds(result: CleanResult) -> list[str]:
    return [issue.kind for issue in result.report.issues]


def test_clean_input_passes_through_unchanged() -> None:
    result = clean(_frame())
    report = result.report
    assert (report.rows_received, report.rows_accepted, report.rows_rejected) == (6, 6, 0)
    assert report.issues == [] and report.gaps == []
    assert result.frame[SOURCE_ROW].tolist() == [1, 2, 3, 4, 5, 6]
    assert all(cols == () for cols in result.frame[IMPUTED])


def test_sample_file_is_clean() -> None:
    raw = read_csv((REPO / "sample_test_input.csv").read_bytes(), max_bytes=10_000_000)
    result = clean(raw)
    assert result.report.rows_accepted == 1000 and result.report.issues == []


@pytest.mark.parametrize(
    "header",
    [
        "Timestamp, Ambient Temp C ,HUMIDITY_PCT,Solar Irradiance (W/m2)",
        "time,temperature,humidity,irradiance",
        "datetime;temp_c;rh;ghi",
    ],
)
def test_header_variants_are_accepted(header: str) -> None:
    sep = ";" if ";" in header else ","
    body = f"{header}\n" + sep.join(["2015-07-01 00:00", "21.5", "60", "0"]) + "\n"
    result = clean(read_csv(body.encode(), max_bytes=10_000))
    assert result.frame["ambient_temp_c"].iloc[0] == 21.5
    assert result.report.columns_renamed


def test_missing_column_message_lists_what_was_found() -> None:
    with pytest.raises(IngestError, match=r"missing required column\(s\): humidity_pct \(found: 'timestamp'"):
        clean(_frame().drop(columns="humidity_pct"))


def test_ambiguous_columns_are_rejected() -> None:
    frame = _frame().assign(temperature=1.0)
    with pytest.raises(IngestError, match="both map to 'ambient_temp_c'"):
        clean(frame)


def test_unsorted_duplicates_and_bad_timestamps() -> None:
    frame = _frame(4).iloc[[2, 0, 1, 3]].reset_index(drop=True)
    frame = _append(frame, "2015-07-01 01:00:00", 99.0)
    frame = _append(frame, "yesterday-ish", 20.0)
    result = clean(frame)
    assert result.frame["timestamp"].is_monotonic_increasing
    assert result.report.duplicates_removed == 1
    assert result.frame["ambient_temp_c"].max() < 99
    assert sorted(_kinds(result)) == ["duplicate_timestamp", "invalid_timestamp"]
    assert result.report.rows_rejected == 2


def test_timezone_and_minutes_are_normalised_to_local_hour() -> None:
    frame = _frame(2)
    frame["timestamp"] = ["2015-07-01T10:30:00+05:30", "2015-07-01 11:00"]
    result = clean(frame)
    assert result.frame["timestamp"].dt.hour.tolist() == [10, 11]
    assert _kinds(result) == ["unaligned_timestamp"]


def test_short_gaps_are_interpolated_in_time() -> None:
    frame = _frame(5)
    frame["ambient_temp_c"] = [20.0, None, None, 26.0, 28.0]
    frame["humidity_pct"] = frame["humidity_pct"].astype(object)
    frame.loc[4, "humidity_pct"] = "n/a"
    result = clean(frame)
    assert result.frame["ambient_temp_c"].tolist() == pytest.approx([20, 22, 24, 26, 28])
    assert result.frame["humidity_pct"].iloc[4] == 50
    assert result.report.rows_imputed == 3 and result.report.values_imputed == 3
    assert result.frame[IMPUTED].tolist()[1] == ("ambient_temp_c",)


def test_long_gaps_reject_rows() -> None:
    frame = _frame(8)
    frame.loc[1:5, "ambient_temp_c"] = np.nan
    result = clean(frame, CleaningLimits(max_impute_gap_hours=3))
    assert result.report.rows_accepted == 3
    assert _kinds(result).count("gap_too_large") == 5
    assert result.report.gaps[0].missing_hours == 5


def test_gap_limit_counts_missing_hours_not_rows() -> None:
    frame = _frame(2)
    frame = _append(frame, "2015-07-01 06:00:00", None)
    frame = _append(frame, "2015-07-01 07:00:00", 30.0)
    result = clean(frame, CleaningLimits(max_impute_gap_hours=3))
    assert result.report.rows_accepted == 3
    assert _kinds(result) == ["gap_too_large"]
    assert result.report.gaps[0].missing_hours == 5


def test_physical_ranges_clip_or_invalidate() -> None:
    frame = _frame(6)
    frame["humidity_pct"] = [50, 102, -3, 140, 50, 50]
    frame["solar_irradiance_wm2"] = [-0.5, 0, 0, 0, 5000, 1505]
    frame["ambient_temp_c"] = [20, 21, 22, 23, 80, 25]
    result = clean(frame)
    out = result.frame
    assert out["humidity_pct"].tolist()[:3] == [50, 100, 0]
    assert out["humidity_pct"].iloc[3] == pytest.approx(25)
    assert out["solar_irradiance_wm2"].iloc[0] == 0 and out["solar_irradiance_wm2"].iloc[5] == 1500
    assert out["ambient_temp_c"].iloc[4] == pytest.approx(24)
    assert result.report.values_clipped == 4
    kinds = _kinds(result)
    assert kinds.count("out_of_range") == 3 and kinds.count("imputed") == 3


def test_non_numeric_values_are_reported_then_imputed() -> None:
    frame = _frame(3).astype(object)
    frame.loc[1, "ambient_temp_c"] = "hot"
    result = clean(frame)
    assert _kinds(result) == ["non_numeric", "imputed"]
    assert result.frame["ambient_temp_c"].iloc[1] == pytest.approx(22.5)


def test_column_without_any_value_rejects_everything() -> None:
    frame = _frame(3)
    frame["solar_irradiance_wm2"] = None
    with pytest.raises(IngestError, match="no usable rows") as excinfo:
        clean(frame)
    assert {i.kind for i in excinfo.value.issues} == {"gap_too_large"}


def test_actual_demand_is_kept_when_present() -> None:
    frame = _frame(2).assign(target_demand_kw=[120.5, "bad"])
    out = clean(frame).frame
    assert out[ACTUAL].iloc[0] == 120.5 and np.isnan(out[ACTUAL].iloc[1])


def test_row_limit() -> None:
    with pytest.raises(IngestError, match="limit is 3"):
        clean(_frame(4), CleaningLimits(max_rows=3))


def test_unparseable_csv() -> None:
    with pytest.raises(IngestError, match="could not parse CSV"):
        read_csv(b'timestamp,temp\n"2015-07-01,20\n', max_bytes=1000)


def test_non_utf8_csv_is_decoded() -> None:
    body = "timestamp,temp,humidity,irradiance,site\n2015-07-01 00:00,20,50,0,Z\xfcrich\n".encode("latin-1")
    assert clean(read_csv(body, max_bytes=1000)).report.rows_accepted == 1


def test_all_timestamps_invalid() -> None:
    frame = _frame(2).assign(timestamp=pd.Series(["", None], dtype=object))
    with pytest.raises(IngestError, match="no usable rows"):
        clean(frame)


def test_leading_gap_uses_nearest_value() -> None:
    frame = _frame(4)
    frame.loc[0, "ambient_temp_c"] = np.nan
    assert clean(frame).frame["ambient_temp_c"].iloc[0] == pytest.approx(frame["ambient_temp_c"].iloc[1])


def test_empty_inputs() -> None:
    with pytest.raises(IngestError, match="no data rows"):
        clean(_frame(0))
    with pytest.raises(IngestError, match="empty"):
        read_csv(b"  \n", max_bytes=100)


def test_oversized_file() -> None:
    with pytest.raises(IngestError, match="limit is 10"):
        read_csv(b"timestamp,a\n1,2\n", max_bytes=10)


def test_issue_list_is_capped() -> None:
    frame = _frame(300)
    frame["humidity_pct"] = 101.0
    report = clean(frame).report
    assert len(report.issues) == 200 and report.issues_truncated == 100
