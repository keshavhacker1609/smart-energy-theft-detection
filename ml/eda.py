"""Exploratory figures for the README and the dashboard's Model page.

Reads the training data and ml/reports/model_selection.json (run ml/train.py
first) and writes PNGs to docs/figures/.

Usage: python ml/eda.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ml"))

from app.features import TARGET, TEMPERATURE, TIMESTAMP, FeatureSpec, build_features  # noqa: E402
from train import HOLDOUT_FRACTION, REPORT_PATH, load_training_data, rmse  # noqa: E402

FIGURES = ROOT / "docs" / "figures"

INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"
THRESHOLD = "#8a8985"
PEAK_BAND = "#f1efe9"

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_MUTED,
        "axes.titlecolor": INK,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "font.size": 10,
        "legend.frameon": False,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
    }
)


def _save(fig: Figure, name: str) -> None:
    fig.savefig(FIGURES / name)
    plt.close(fig)
    print(f"wrote docs/figures/{name}")


def hourly_profile(df: pd.DataFrame) -> None:
    hour = df[TIMESTAMP].dt.hour
    grouped = df.groupby(hour)[TARGET]
    mean, q25, q75 = grouped.mean(), grouped.quantile(0.25), grouped.quantile(0.75)

    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.axvspan(17.5, 22.5, color=PEAK_BAND, zorder=0)
    ax.text(20, 245, "peak window 18-22", ha="center", color=INK_MUTED, fontsize=9)
    ax.fill_between(
        mean.index, q25, q75, color=SERIES_1, alpha=0.18, linewidth=0, label="interquartile range"
    )
    ax.plot(mean.index, mean, color=SERIES_1, linewidth=2, marker="o", markersize=4, label="mean demand")
    for level, label in ((160, "160 kW storage threshold"), (200, "200 kW overload")):
        ax.axhline(level, color=THRESHOLD, linewidth=1, linestyle=(0, (4, 3)))
        ax.text(-0.4, level + 3, label, color=INK_MUTED, fontsize=8)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlim(-0.5, 23.5)
    ax.set_ylim(60, 260)
    ax.set_xlabel("hour of day")
    ax.set_ylabel("demand (kW)")
    ax.set_title("Demand by hour of day")
    ax.legend(loc="upper left", fontsize=8)
    _save(fig, "hourly_profile.png")


def cooling_knee(df: pd.DataFrame, spec: FeatureSpec) -> None:
    """Demand with the hourly mean removed, against temperature."""
    hour = df[TIMESTAMP].dt.hour
    adjusted = df[TARGET] - df.groupby(hour)[TARGET].transform("mean")
    temperature = df[TEMPERATURE]
    bins = pd.cut(temperature, list(range(-4, 42)))
    binned = adjusted.groupby(bins, observed=True).mean()
    centers = [interval.mid for interval in binned.index]

    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.scatter(temperature, adjusted, s=6, color=SERIES_1, alpha=0.25, linewidths=0, label="hourly reading")
    ax.plot(centers, binned.to_numpy(), color=SERIES_2, linewidth=2, label="1 C bin mean")
    ax.axvline(spec.cooling_base_c, color=THRESHOLD, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(
        spec.cooling_base_c + 0.4,
        adjusted.max() * 0.92,
        f"learned cooling knee {spec.cooling_base_c:g} C",
        color=INK_MUTED,
        fontsize=9,
    )
    ax.set_xlabel("ambient temperature (C)")
    ax.set_ylabel("demand minus hourly mean (kW)")
    ax.set_title("Cooling load switches on above the knee")
    ax.legend(loc="upper left", fontsize=8)
    _save(fig, "cooling_knee.png")


def holdout_diagnostics(df: pd.DataFrame, spec: FeatureSpec) -> None:
    split = int(len(df) * (1 - HOLDOUT_FRACTION))
    development, holdout = df.iloc[:split], df.iloc[split:]
    model = LinearRegression().fit(build_features(development, spec), development[TARGET])
    predicted = model.predict(build_features(holdout, spec))
    actual = holdout[TARGET].to_numpy()
    residual = actual - predicted
    score = rmse(actual, predicted)

    window = holdout.iloc[-24 * 7 :]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.plot(window[TIMESTAMP], actual[-len(window) :], color=SERIES_1, linewidth=1.6, label="actual")
    ax.plot(window[TIMESTAMP], predicted[-len(window) :], color=SERIES_2, linewidth=1.6, label="predicted")
    ax.set_ylabel("demand (kW)")
    ax.set_title(f"Time-ordered holdout, last 7 days (holdout RMSE {score:.2f} kW)")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    fig.autofmt_xdate()
    _save(fig, "holdout_timeseries.png")

    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    lo, hi = min(actual.min(), predicted.min()) - 5, max(actual.max(), predicted.max()) + 5
    ax.plot([lo, hi], [lo, hi], color=THRESHOLD, linewidth=1, linestyle=(0, (4, 3)))
    ax.scatter(actual, predicted, s=8, color=SERIES_1, alpha=0.45, linewidths=0)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("actual (kW)")
    ax.set_ylabel("predicted (kW)")
    ax.set_title("Predicted vs actual, holdout")
    _save(fig, "holdout_pred_vs_actual.png")

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), sharey=True)
    axes[0].scatter(holdout[TEMPERATURE], residual, s=7, color=SERIES_1, alpha=0.4, linewidths=0)
    axes[0].set_xlabel("ambient temperature (C)")
    axes[0].set_ylabel("residual (kW)")
    axes[0].set_title("Residual vs temperature")
    hours = holdout[TIMESTAMP].dt.hour
    axes[1].boxplot(
        [residual[hours.to_numpy() == h] for h in range(24)],
        positions=range(24),
        widths=0.6,
        showfliers=False,
        medianprops={"color": SERIES_2},
        boxprops={"color": INK_MUTED},
        whiskerprops={"color": INK_MUTED},
        capprops={"color": INK_MUTED},
    )
    axes[1].set_xticks(range(0, 24, 3), [str(h) for h in range(0, 24, 3)])
    axes[1].set_xlabel("hour of day")
    axes[1].set_title("Residual by hour")
    for ax in axes:
        ax.axhline(0, color=THRESHOLD, linewidth=1)
    _save(fig, "residuals.png")


def model_comparison() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    rows = sorted(report["candidates"].items(), key=lambda kv: kv[1]["cv_mean"], reverse=True)
    names = [name.replace("_", " ") for name, _ in rows]
    scores = [values["cv_mean"] for _, values in rows]
    colors = [SERIES_1 if name == report["selected"] else "#a7c6ec" for name, _ in rows]

    fig, ax = plt.subplots(figsize=(8, 3.6))
    bars = ax.barh(names, scores, color=colors, height=0.6)
    for bar, score in zip(bars, scores, strict=True):
        ax.text(
            bar.get_width() + 0.6,
            bar.get_y() + bar.get_height() / 2,
            f"{score:.2f}",
            va="center",
            color=INK,
            fontsize=9,
        )
    ax.set_xlabel("mean RMSE over 5 time-ordered folds (kW)")
    ax.set_title("Model comparison, TimeSeriesSplit CV")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(scores) * 1.12)
    _save(fig, "model_comparison.png")


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    df = load_training_data()
    spec = FeatureSpec.load()
    hourly_profile(df)
    cooling_knee(df, spec)
    holdout_diagnostics(df, spec)
    model_comparison()


if __name__ == "__main__":
    main()
