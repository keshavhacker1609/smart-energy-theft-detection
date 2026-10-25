from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.features import (
    HOUR_COLUMNS,
    INPUT_COLUMNS,
    TARGET,
    FeatureSpec,
    build_features,
    default_spec,
    feature_names,
)

REPO = Path(__file__).resolve().parents[2]
SPEC = FeatureSpec(cooling_base_c=24.0, heating_base_c=10.0)


def _rows(hours: list[int], temps: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [f"2015-07-01 {h:02d}:00:00" for h in hours],
            "ambient_temp_c": temps,
            "humidity_pct": [50.0] * len(hours),
            "solar_irradiance_wm2": [100.0] * len(hours),
        }
    )


def test_columns_follow_declared_order() -> None:
    out = build_features(_rows([0, 12], [20.0, 30.0]), SPEC)
    assert list(out.columns) == feature_names()
    assert out.shape == (2, len(feature_names()))


def test_hour_zero_is_reference_level() -> None:
    out = build_features(_rows(list(range(24)), [20.0] * 24), SPEC)
    hour_block = out[list(HOUR_COLUMNS)].to_numpy()
    assert hour_block[0].sum() == 0
    np.testing.assert_array_equal(hour_block[1:], np.eye(23, dtype=int))


@pytest.mark.parametrize(
    ("temp", "cdd", "hdd"),
    [(24.0, 0.0, 0.0), (24.5, 0.5, 0.0), (38.0, 14.0, 0.0), (10.0, 0.0, 0.0), (4.0, 0.0, 6.0)],
)
def test_degree_days_hinge_at_learned_knees(temp: float, cdd: float, hdd: float) -> None:
    out = build_features(_rows([12], [temp]), SPEC)
    assert out["cdd"].iloc[0] == pytest.approx(cdd)
    assert out["hdd"].iloc[0] == pytest.approx(hdd)


def test_cooling_term_is_unbounded_for_extrapolation() -> None:
    out = build_features(_rows([12, 12], [45.0, 55.0]), SPEC)
    assert out["cdd"].tolist() == [21.0, 31.0]


def test_index_and_row_order_preserved() -> None:
    df = _rows([23, 5, 18], [30.0, 15.0, 25.0])
    df.index = [7, 3, 11]
    out = build_features(df, SPEC)
    assert out.index.tolist() == [7, 3, 11]
    assert out.loc[7, "h_23"] == 1 and out.loc[3, "h_05"] == 1 and out.loc[11, "h_18"] == 1


def test_rows_are_independent() -> None:
    """No cross-row state: a row's features must not depend on its neighbours."""
    df = _rows([1, 9, 17, 22], [5.0, 26.0, 33.0, 21.0])
    batch = build_features(df, SPEC)
    for i in range(len(df)):
        single = build_features(df.iloc[[i]], SPEC)
        pd.testing.assert_frame_equal(single, batch.iloc[[i]])


def test_target_and_extra_columns_are_ignored() -> None:
    df = _rows([3], [20.0]).assign(**{TARGET: 999.0, "noise": 1.0})
    assert TARGET not in build_features(df, SPEC).columns


def test_missing_column_is_reported() -> None:
    with pytest.raises(ValueError, match="humidity_pct"):
        build_features(_rows([0], [20.0]).drop(columns="humidity_pct"), SPEC)


def test_missing_value_is_reported() -> None:
    df = _rows([0, 1], [20.0, np.nan])
    with pytest.raises(ValueError, match="ambient_temp_c"):
        build_features(df, SPEC)


def test_bad_timestamp_is_reported() -> None:
    df = _rows([0], [20.0]).assign(timestamp=["not a time"])
    with pytest.raises(ValueError, match="unparseable"):
        build_features(df, SPEC)


def test_spec_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    SPEC.save(path)
    assert FeatureSpec.load(path) == SPEC


def test_quickml_export_matches_pipeline() -> None:
    """Training export and inference features come from the same code path."""
    raw = pd.read_csv(REPO / "ml" / "data" / "train_telemetry.csv")
    export = pd.read_csv(REPO / "ml" / "quickml_train.csv")
    rebuilt = build_features(raw[list(INPUT_COLUMNS)], default_spec())
    assert list(export.columns) == [*feature_names(), TARGET]
    np.testing.assert_allclose(export[feature_names()].to_numpy(float), rebuilt.to_numpy(float))
    np.testing.assert_allclose(export[TARGET], raw[TARGET])
