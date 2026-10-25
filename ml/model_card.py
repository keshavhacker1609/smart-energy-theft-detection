"""Build the model card served by GET /api/model from the training run.

Reads ml/reports/model_selection.json (written by ml/train.py) and the
training data, and writes backend/app/model_card.json.

Usage: python ml/model_card.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ml"))

from app.features import TARGET, TEMPERATURE, TIMESTAMP, FeatureSpec, build_features, feature_names
from train import HOLDOUT_FRACTION, REPORT_PATH, load_training_data, rmse

CARD_PATH = ROOT / "backend" / "app" / "model_card.json"
HOLDOUT_SERIES_HOURS = 24 * 7

FEATURE_DESCRIPTIONS = {
    "hour": "One-hot hour of day h_01..h_23 (hour 00 is the reference level)",
    "cdd": "Cooling degrees: max(0, temperature - {cooling:g} C)",
    "hdd": "Heating degrees: max(0, {heating:g} C - temperature)",
    "humidity_pct": "Relative humidity, raw",
    "solar_irradiance_wm2": "Solar irradiance, raw",
}
LIMITATIONS = [
    "Hourly demand only; no lagged demand is available at inference time, so autocorrelated "
    "deviations (outages, events) are not captured.",
    "Cooling response is linear above the knee; training covers up to 38 C, beyond that the "
    "slope is extrapolated.",
    "The heating knee is weakly identified because winter data is short; it has no effect on "
    "summer forecasts.",
    "Weekday/weekend and holiday effects were tested and found negligible in this data; a site "
    "with strong calendar effects would need them reintroduced.",
]


def hourly_profile(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(df[TIMESTAMP].dt.hour)[TARGET]
    return pd.DataFrame(
        {
            "hour": range(24),
            "mean_kw": grouped.mean().to_numpy(),
            "q25_kw": grouped.quantile(0.25).to_numpy(),
            "q75_kw": grouped.quantile(0.75).to_numpy(),
        }
    )


def cooling_curve(df: pd.DataFrame) -> pd.DataFrame:
    """Demand minus its hourly mean, averaged in 1 C temperature bins."""
    adjusted = df[TARGET] - df.groupby(df[TIMESTAMP].dt.hour)[TARGET].transform("mean")
    bins = np.floor(df[TEMPERATURE]).astype(int)
    grouped = adjusted.groupby(bins)
    return pd.DataFrame(
        {
            "temp_c": grouped.mean().index.to_numpy() + 0.5,
            "mean_adjusted_kw": grouped.mean().to_numpy(),
            "count": grouped.size().to_numpy(),
        }
    )


def holdout_predictions(df: pd.DataFrame, spec: FeatureSpec) -> tuple[pd.DataFrame, np.ndarray]:
    split = int(len(df) * (1 - HOLDOUT_FRACTION))
    development, holdout = df.iloc[:split], df.iloc[split:]
    model = LinearRegression().fit(build_features(development, spec), development[TARGET])
    return holdout, np.asarray(model.predict(build_features(holdout, spec)))


def _records(frame: pd.DataFrame, digits: int = 2) -> list[dict[str, Any]]:
    return [
        {
            str(k): (round(float(v), digits) if isinstance(v, (float, np.floating)) else v)
            for k, v in row.items()
        }
        for row in frame.to_dict(orient="records")
    ]


def build_card() -> dict[str, Any]:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    df = load_training_data()
    spec = FeatureSpec.load()
    selected = report["selected"]
    holdout, predicted = holdout_predictions(df, spec)
    actual = holdout[TARGET].to_numpy()
    residual = actual - predicted
    hours = holdout[TIMESTAMP].dt.hour.to_numpy()
    tail = holdout.iloc[-HOLDOUT_SERIES_HOURS:]

    descriptions = {
        k: v.format(cooling=spec.cooling_base_c, heating=spec.heating_base_c)
        for k, v in FEATURE_DESCRIPTIONS.items()
    }
    return {
        "selected": selected,
        "algorithm": "Ordinary least squares linear regression",
        "validation_rmse_kw": report["candidates"][selected]["cv_mean"],
        "holdout_rmse_kw": round(rmse(actual, predicted), 3),
        "selection_rule": (
            "Lowest mean TimeSeriesSplit RMSE among models that extrapolate in temperature; "
            "candidates within 1% are tied and the simplest wins."
        ),
        "why": (
            "Demand is a step function of hour of day plus a linear cooling load above "
            f"{spec.cooling_base_c:g} C. The forecast horizon is hotter than the training period, "
            "and tree ensembles cannot predict beyond the largest temperature they were trained on, "
            "so their error grows fold by fold; the linear model's does not."
        ),
        "training": {
            "rows": len(df),
            "start": f"{df[TIMESTAMP].iloc[0]:%Y-%m-%d %H:%M}",
            "end": f"{df[TIMESTAMP].iloc[-1]:%Y-%m-%d %H:%M}",
            "n_splits": report["n_splits"],
            "holdout_fraction": report["holdout_fraction"],
        },
        "feature_spec": report["feature_spec"],
        "features": [{"name": k, "description": v} for k, v in descriptions.items()],
        "feature_columns": feature_names(),
        "candidates": [{"name": name, **values} for name, values in report["candidates"].items()],
        "optional_terms_cv_mean": report["optional_terms_cv_mean"],
        "coefficients": report["selected_coefficients"],
        "hourly_profile": _records(hourly_profile(df)),
        "cooling_curve": _records(cooling_curve(df)),
        "holdout_series": [
            {
                "timestamp": f"{ts:%Y-%m-%d %H:%M}",
                "actual_kw": round(float(a), 2),
                "predicted_kw": round(float(p), 2),
            }
            for ts, a, p in zip(tail[TIMESTAMP], actual[-len(tail) :], predicted[-len(tail) :], strict=True)
        ],
        "holdout_scatter": [
            [round(float(a), 1), round(float(p), 1)] for a, p in zip(actual, predicted, strict=True)
        ],
        "residual_by_hour": [
            {
                "hour": h,
                "median_kw": round(float(np.median(residual[hours == h])), 2),
                "q25_kw": round(float(np.quantile(residual[hours == h], 0.25)), 2),
                "q75_kw": round(float(np.quantile(residual[hours == h], 0.75)), 2),
            }
            for h in range(24)
        ],
        "limitations": LIMITATIONS,
    }


def main() -> None:
    CARD_PATH.write_text(json.dumps(build_card(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {CARD_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
