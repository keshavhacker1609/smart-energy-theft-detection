"""Local stand-in for the QuickML endpoint, for development and CI only.

Fits the selected model (OLS) on ml/quickml_train.csv and serves it over HTTP
using the same request/response format as the QuickML client, so predict.py,
test_eval.py and the backend can be exercised without Catalyst credentials.
It is never deployed.

Usage: python ml/local_endpoint.py --port 8765
       QUICKML_ENDPOINT_URL=http://127.0.0.1:8765/predict python test_eval.py
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.features import TARGET, feature_names  # noqa: E402

EXPORT_PATH = ROOT / "ml" / "quickml_train.csv"


def fit_reference_model(path: Path = EXPORT_PATH) -> LinearRegression:
    table = pd.read_csv(path)
    return LinearRegression().fit(table[feature_names()], table[TARGET])


def make_handler(model: LinearRegression) -> type[BaseHTTPRequestHandler]:
    columns = feature_names()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                rows = json.loads(self.rfile.read(length))["data"]
                frame = pd.DataFrame(rows)
                missing = [c for c in columns if c not in frame.columns]
                if missing:
                    raise ValueError(f"missing features: {missing}")
                predictions = np.asarray(model.predict(frame[columns]), dtype=float)
                self._reply(200, {"predictions": predictions.round(4).tolist()})
            except (KeyError, ValueError, TypeError) as exc:
                self._reply(400, {"error": str(exc)})

        def _reply(self, status: int, body: dict[str, object]) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the reference model locally.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(fit_reference_model()))
    print(f"reference endpoint on http://{args.host}:{args.port}/predict")
    server.serve_forever()


if __name__ == "__main__":
    main()
