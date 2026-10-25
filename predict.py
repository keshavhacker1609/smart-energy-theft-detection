"""Hourly demand predictions from the published QuickML endpoint.

Contract: predict(input_df) returns one finite prediction (kW) per input row,
in input order. Features are built by the same module the backend and the
training export use (backend/app/features.py).

Configuration is read from the environment, or from a .env file next to this
script: QUICKML_ENDPOINT_URL (required), QUICKML_API_KEY, QUICKML_AUTH_SCHEME,
QUICKML_EXTRA_HEADERS, QUICKML_BATCH_SIZE, QUICKML_TIMEOUT_S.

Usage: python predict.py --input sample_test_input.csv --output predictions.csv
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.features import TARGET, TIMESTAMP, build_features  # noqa: E402
from app.quickml_client import QuickMLClient, QuickMLSettings  # noqa: E402


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from KEY=VALUE lines without overriding existing values."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def predict(input_df: pd.DataFrame) -> np.ndarray:
    """Predicted demand (kW) for each row of input_df, order preserved.

    input_df needs columns timestamp, ambient_temp_c, humidity_pct,
    solar_irradiance_wm2. Raises if the endpoint cannot be reached.
    """
    _load_dotenv(ROOT / ".env")
    client = QuickMLClient(QuickMLSettings.from_env())
    features = build_features(input_df.reset_index(drop=True))
    predictions = client.predict(features)
    if len(predictions) != len(input_df):
        raise RuntimeError(f"expected {len(input_df)} predictions, got {len(predictions)}")
    return predictions


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="sample_test_input.csv", type=Path)
    parser.add_argument("--output", default="predictions.csv", type=Path)
    args = parser.parse_args(argv)

    input_df = pd.read_csv(args.input)
    predictions = predict(input_df)
    pd.DataFrame({TIMESTAMP: input_df[TIMESTAMP], TARGET: np.round(predictions, 2)}).to_csv(
        args.output, index=False
    )
    print(f"wrote {len(predictions)} predictions to {args.output}")


if __name__ == "__main__":
    main()
