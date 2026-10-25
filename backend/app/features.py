"""Feature pipeline shared by training export, the API backend and predict.py.

This module is the only place model features are constructed. Keeping it
dependency-light (numpy + pandas) lets predict.py import it without pulling in
the web stack.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

TIMESTAMP = "timestamp"
TEMPERATURE = "ambient_temp_c"
HUMIDITY = "humidity_pct"
IRRADIANCE = "solar_irradiance_wm2"
TARGET = "target_demand_kw"

WEATHER_COLUMNS: tuple[str, ...] = (TEMPERATURE, HUMIDITY, IRRADIANCE)
INPUT_COLUMNS: tuple[str, ...] = (TIMESTAMP, *WEATHER_COLUMNS)

# Hour 00 is the reference level; its effect is absorbed by the model intercept.
# Dropping it keeps the design matrix full-rank for any linear solver QuickML uses.
HOUR_COLUMNS: tuple[str, ...] = tuple(f"h_{h:02d}" for h in range(1, 24))

DEFAULT_SPEC_PATH = Path(__file__).with_name("feature_spec.json")


@dataclass(frozen=True)
class FeatureSpec:
    """Parameters learned during training that inference must reproduce exactly."""

    cooling_base_c: float
    heating_base_c: float

    @classmethod
    def load(cls, path: Path = DEFAULT_SPEC_PATH) -> FeatureSpec:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls(
            cooling_base_c=float(payload["cooling_base_c"]),
            heating_base_c=float(payload["heating_base_c"]),
        )

    def save(self, path: Path = DEFAULT_SPEC_PATH) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


@lru_cache(maxsize=1)
def default_spec() -> FeatureSpec:
    return FeatureSpec.load()


def feature_names() -> list[str]:
    """Column order of the model input, identical for training and inference.

    Temperature enters only through the degree-day terms: alongside raw
    temperature they are collinear and the knee locations become unidentifiable.
    """
    return [*HOUR_COLUMNS, "cdd", "hdd", HUMIDITY, IRRADIANCE]


def build_features(df: pd.DataFrame, spec: FeatureSpec | None = None) -> pd.DataFrame:
    """Map raw telemetry rows to model features, preserving row order and index.

    Expects already-cleaned input: required columns present, no missing values.
    """
    spec = spec or default_spec()
    missing = [c for c in INPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")

    timestamps = pd.to_datetime(df[TIMESTAMP], errors="coerce")
    if timestamps.isna().any():
        bad = df.loc[timestamps.isna(), TIMESTAMP].head(3).tolist()
        raise ValueError(f"unparseable timestamps: {bad}")

    weather = df.loc[:, list(WEATHER_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    if weather.isna().any().any():
        cols = weather.columns[weather.isna().any()].tolist()
        raise ValueError(f"missing or non-numeric values in: {', '.join(cols)}")

    hours = timestamps.dt.hour.to_numpy()
    hour_matrix = (hours[:, None] == np.arange(1, 24)[None, :]).astype(np.int8)
    temperature = weather[TEMPERATURE].to_numpy(dtype=float)

    features = pd.DataFrame(hour_matrix, columns=list(HOUR_COLUMNS), index=df.index)
    features["cdd"] = np.maximum(0.0, temperature - spec.cooling_base_c)
    features["hdd"] = np.maximum(0.0, spec.heating_base_c - temperature)
    features[HUMIDITY] = weather[HUMIDITY].to_numpy(dtype=float)
    features[IRRADIANCE] = weather[IRRADIANCE].to_numpy(dtype=float)
    return features[feature_names()]
