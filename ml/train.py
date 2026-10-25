"""Model selection for the demand forecaster.

Learns the cooling/heating knees, compares candidate models with time-ordered
cross-validation, writes the learned feature spec consumed by the shared
pipeline, and exports the engineered training table uploaded to QuickML.

Usage: python ml/train.py
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.base import RegressorMixin, clone
from sklearn.linear_model import ElasticNetCV, LinearRegression, RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.features import (
    DEFAULT_SPEC_PATH,
    HUMIDITY,
    IRRADIANCE,
    TARGET,
    TEMPERATURE,
    TIMESTAMP,
    FeatureSpec,
    build_features,
    feature_names,
)

DATA_PATH = ROOT / "ml" / "data" / "train_telemetry.csv"
REPORT_PATH = ROOT / "ml" / "reports" / "model_selection.json"
EXPORT_PATH = ROOT / "ml" / "quickml_train.csv"
DEV_EXPORT_PATH = ROOT / "ml" / "quickml_train_dev.csv"

N_SPLITS = 5
HOLDOUT_FRACTION = 0.2
COOLING_GRID = np.arange(20.0, 28.01, 0.25)
HEATING_GRID = np.arange(0.0, 20.01, 0.5)
SEED = 7
L1_RATIOS = [0.1, 0.5, 0.9, 1.0]


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(y_true) - np.asarray(y_pred)) ** 2)))


def load_training_data(path: Path = DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    df[TIMESTAMP] = pd.to_datetime(df[TIMESTAMP])
    return df.sort_values(TIMESTAMP, kind="stable").reset_index(drop=True)


def cv_rmse(
    fit_predict: Callable[[pd.DataFrame, pd.DataFrame], np.ndarray],
    df: pd.DataFrame,
    n_splits: int = N_SPLITS,
) -> list[float]:
    """Expanding-window CV; fit_predict(train_rows, test_rows) returns predictions."""
    scores = []
    for train_idx, test_idx in TimeSeriesSplit(n_splits=n_splits).split(df):
        train, test = df.iloc[train_idx], df.iloc[test_idx]
        scores.append(rmse(test[TARGET].to_numpy(), fit_predict(train, test)))
    return scores


def search_knees(df: pd.DataFrame) -> tuple[FeatureSpec, float]:
    """Grid-search the CDD/HDD base temperatures with an OLS model under TSCV."""
    best: tuple[float, FeatureSpec] | None = None
    splits = list(TimeSeriesSplit(n_splits=N_SPLITS).split(df))
    y = df[TARGET].to_numpy()
    for cooling in COOLING_GRID:
        for heating in HEATING_GRID:
            if heating > cooling:
                continue
            spec = FeatureSpec(round(float(cooling), 2), round(float(heating), 2))
            design = np.c_[np.ones(len(df)), build_features(df, spec).to_numpy(float)]
            fold_scores = []
            for train_idx, test_idx in splits:
                coef, *_ = np.linalg.lstsq(design[train_idx], y[train_idx], rcond=None)
                fold_scores.append(rmse(y[test_idx], design[test_idx] @ coef))
            score = float(np.mean(fold_scores))
            if best is None or score < best[0]:
                best = (score, spec)
    assert best is not None
    return best[1], best[0]


@dataclass(frozen=True)
class Candidate:
    name: str
    fit_predict: Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]
    extrapolates: bool


def _raw_matrix(df: pd.DataFrame, with_calendar: bool) -> pd.DataFrame:
    out = df[[TEMPERATURE, HUMIDITY, IRRADIANCE]].copy()
    if with_calendar:
        out["hour"] = df[TIMESTAMP].dt.hour
        out["dayofweek"] = df[TIMESTAMP].dt.dayofweek
    return out


def _sk_on_features(model: RegressorMixin, spec: FeatureSpec) -> Callable[..., np.ndarray]:
    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        fitted = clone(model).fit(build_features(train, spec), train[TARGET])
        return np.asarray(fitted.predict(build_features(test, spec)))

    return fit_predict


def _sk_on_raw(model: RegressorMixin, with_calendar: bool) -> Callable[..., np.ndarray]:
    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        fitted = clone(model).fit(_raw_matrix(train, with_calendar), train[TARGET])
        return np.asarray(fitted.predict(_raw_matrix(test, with_calendar)))

    return fit_predict


def _hybrid(spec: FeatureSpec) -> Callable[..., np.ndarray]:
    """OLS on engineered features, then a shallow GBM on its residuals."""

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        linear = LinearRegression().fit(build_features(train, spec), train[TARGET])
        residual = train[TARGET] - linear.predict(build_features(train, spec))
        booster = _gbm(n_estimators=200, learning_rate=0.03, num_leaves=8)
        booster.fit(_raw_matrix(train, with_calendar=True), residual)
        return np.asarray(
            linear.predict(build_features(test, spec))
            + booster.predict(_raw_matrix(test, with_calendar=True))
        )

    return fit_predict


def _with_extra_term(spec: FeatureSpec, term: str) -> Callable[..., np.ndarray]:
    """OLS with one candidate term appended, used to test optional features."""

    def augment(df: pd.DataFrame) -> pd.DataFrame:
        features = build_features(df, spec)
        hour = df[TIMESTAMP].dt.hour
        if term == "cdd_x_daytime":
            features[term] = features["cdd"] * hour.between(7, 22).to_numpy()
        elif term == "cdd_squared":
            features[term] = features["cdd"] ** 2
        elif term == "is_weekend":
            features[term] = (df[TIMESTAMP].dt.dayofweek >= 5).astype(int).to_numpy()
        else:
            raise ValueError(term)
        return features

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        fitted = LinearRegression().fit(augment(train), train[TARGET])
        return np.asarray(fitted.predict(augment(test)))

    return fit_predict


def _gbm(**params: Any) -> LGBMRegressor:
    return LGBMRegressor(random_state=SEED, verbose=-1, **params)


def _scaled(model: RegressorMixin) -> Pipeline:
    return make_pipeline(StandardScaler(), model)


def candidates(spec: FeatureSpec) -> list[Candidate]:
    return [
        Candidate("baseline_linear_raw_weather", _sk_on_raw(LinearRegression(), False), True),
        Candidate(
            "lightgbm_raw_weather_hour", _sk_on_raw(_gbm(n_estimators=400, learning_rate=0.03), True), False
        ),
        Candidate("linear_hour_cdd_hdd", _sk_on_features(LinearRegression(), spec), True),
        Candidate(
            "ridge_hour_cdd_hdd", _sk_on_features(_scaled(RidgeCV(alphas=np.logspace(-3, 2, 20))), spec), True
        ),
        Candidate(
            "elasticnet_hour_cdd_hdd",
            _sk_on_features(
                _scaled(ElasticNetCV(l1_ratio=L1_RATIOS, cv=TimeSeriesSplit(3), random_state=SEED)),
                spec,
            ),
            True,
        ),
        Candidate(
            "lightgbm_hour_cdd_hdd", _sk_on_features(_gbm(n_estimators=400, learning_rate=0.03), spec), False
        ),
        Candidate("hybrid_linear_plus_gbm_residual", _hybrid(spec), True),
    ]


def select_model(results: dict[str, dict[str, object]], tolerance: float = 0.01) -> str:
    """Lowest CV RMSE among models that extrapolate in temperature.

    Candidates within `tolerance` of the best are treated as tied, and the first
    of them in declaration order (simplest first) wins.
    """
    eligible = {k: float(v["cv_mean"]) for k, v in results.items() if v["extrapolates"]}  # type: ignore[arg-type]
    best = min(eligible.values())
    return next(k for k, score in eligible.items() if score <= best * (1 + tolerance))


def main() -> None:
    df = load_training_data()
    split = int(len(df) * (1 - HOLDOUT_FRACTION))
    development, holdout = df.iloc[:split], df.iloc[split:]

    # Knees are learned on the development window only so the holdout stays unseen.
    spec, knee_cv = search_knees(development)
    print(
        f"learned knees: cooling={spec.cooling_base_c} C heating={spec.heating_base_c} C "
        f"(dev TSCV RMSE {knee_cv:.3f})"
    )

    results: dict[str, dict[str, object]] = {}
    for candidate in candidates(spec):
        folds = cv_rmse(candidate.fit_predict, df)
        holdout_pred = candidate.fit_predict(development, holdout)
        results[candidate.name] = {
            "cv_folds": [round(s, 3) for s in folds],
            "cv_mean": round(float(np.mean(folds)), 3),
            "holdout_rmse": round(rmse(holdout[TARGET].to_numpy(), holdout_pred), 3),
            "extrapolates": candidate.extrapolates,
        }
        print(
            f"{candidate.name:34s} cv={np.mean(folds):7.3f} folds={np.round(folds, 2)} "
            f"holdout={results[candidate.name]['holdout_rmse']}"
        )

    optional_terms = {}
    for term in ("cdd_x_daytime", "cdd_squared", "is_weekend"):
        folds = cv_rmse(_with_extra_term(spec, term), df)
        optional_terms[term] = round(float(np.mean(folds)), 3)
        print(f"linear + {term:24s} cv={np.mean(folds):7.3f}")

    selected = select_model(results)
    print(f"selected: {selected}")
    final = LinearRegression().fit(build_features(df, spec), df[TARGET])
    in_sample = rmse(df[TARGET].to_numpy(), final.predict(build_features(df, spec)))

    if selected != "linear_hour_cdd_hdd":
        raise SystemExit(f"selection changed to {selected}; update the QuickML algorithm and this script")

    spec.save(DEFAULT_SPEC_PATH)
    export = build_features(df, spec)
    export[TARGET] = df[TARGET].to_numpy()
    export.to_csv(EXPORT_PATH, index=False)
    export.iloc[:split].to_csv(DEV_EXPORT_PATH, index=False)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "feature_spec": {
                    "cooling_base_c": spec.cooling_base_c,
                    "heating_base_c": spec.heating_base_c,
                },
                "knee_search_dev_cv_rmse": round(knee_cv, 3),
                "n_splits": N_SPLITS,
                "holdout_fraction": HOLDOUT_FRACTION,
                "candidates": results,
                "optional_terms_cv_mean": optional_terms,
                "selected": selected,
                "selected_in_sample_rmse": round(in_sample, 3),
                "selected_coefficients": {
                    "intercept": round(float(final.intercept_), 4),
                    **{k: round(float(v), 4) for k, v in zip(feature_names(), final.coef_, strict=True)},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for path in (DEFAULT_SPEC_PATH, EXPORT_PATH, DEV_EXPORT_PATH, REPORT_PATH):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
