"""Score the configured endpoint on the time-ordered holdout (last 20% of training data).

Runs the exact predict.py path, so the number reflects the live deployment
rather than the notebook. Note: a QuickML model trained on the full export has
seen these rows; for a strictly out-of-sample figure, train it on
ml/quickml_train_dev.csv instead.

Usage: python ml/holdout_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml"))

from app.features import INPUT_COLUMNS, TARGET  # noqa: E402
from predict import predict  # noqa: E402
from train import HOLDOUT_FRACTION, load_training_data, rmse  # noqa: E402


def main() -> None:
    df = load_training_data()
    holdout = df.iloc[int(len(df) * (1 - HOLDOUT_FRACTION)) :]
    raw = holdout[list(INPUT_COLUMNS)].copy()
    raw["timestamp"] = raw["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    predictions = predict(raw)
    actual = holdout[TARGET].to_numpy()
    bias = float(np.mean(predictions - actual))
    print(f"rows={len(holdout)} window={holdout['timestamp'].iloc[0]} .. {holdout['timestamp'].iloc[-1]}")
    print(f"holdout RMSE={rmse(actual, predictions):.3f} kW  bias={bias:+.3f} kW")


if __name__ == "__main__":
    main()
