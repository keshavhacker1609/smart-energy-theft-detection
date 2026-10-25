"""HTTP client for the published QuickML regression endpoint.

The wire format is isolated in `encode_batch` and `decode_predictions` so it
can be aligned with the sample request shown in the Catalyst console without
touching callers. Auth and extra headers come from the environment.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import requests

from app.features import TARGET

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
PREDICTION_KEYS = ("predictions", "prediction", "result", "results", "data", "output")


class QuickMLError(RuntimeError):
    """The endpoint could not produce a valid prediction for every row."""


@dataclass(frozen=True)
class QuickMLSettings:
    endpoint_url: str
    api_key: str | None = None
    auth_scheme: str = ""
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    timeout_s: float = 15.0
    batch_size: int = 200
    max_retries: int = 3
    backoff_s: float = 0.5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> QuickMLSettings:
        env = os.environ if env is None else env
        url = env.get("QUICKML_ENDPOINT_URL", "").strip()
        if not url:
            raise QuickMLError("QUICKML_ENDPOINT_URL is not set")
        raw_headers = env.get("QUICKML_EXTRA_HEADERS", "").strip()
        try:
            extra = json.loads(raw_headers) if raw_headers else {}
        except json.JSONDecodeError as exc:
            raise QuickMLError(f"QUICKML_EXTRA_HEADERS is not valid JSON: {exc}") from exc
        if not isinstance(extra, dict):
            raise QuickMLError("QUICKML_EXTRA_HEADERS must be a JSON object")
        return cls(
            endpoint_url=url,
            api_key=env.get("QUICKML_API_KEY") or None,
            auth_scheme=env.get("QUICKML_AUTH_SCHEME", "").strip(),
            extra_headers={str(k): str(v) for k, v in extra.items()},
            timeout_s=float(env.get("QUICKML_TIMEOUT_S", cls.timeout_s)),
            batch_size=int(env.get("QUICKML_BATCH_SIZE", cls.batch_size)),
            max_retries=int(env.get("QUICKML_MAX_RETRIES", cls.max_retries)),
            backoff_s=float(env.get("QUICKML_BACKOFF_S", cls.backoff_s)),
        )

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"{self.auth_scheme} {self.api_key}".strip()
        headers.update(self.extra_headers)
        return headers


def encode_batch(features: pd.DataFrame) -> dict[str, Any]:
    records = [
        {column: _json_number(value) for column, value in row.items()}
        for row in features.to_dict(orient="records")
    ]
    return {"data": records}


def decode_predictions(body: Any, expected: int) -> np.ndarray:
    """Extract one finite float per row from the endpoint response."""
    values = body
    if isinstance(body, Mapping):
        key = next((k for k in PREDICTION_KEYS if k in body), None)
        if key is None:
            raise QuickMLError(f"response has no prediction field; keys: {sorted(body)}")
        values = body[key]
        if isinstance(values, Mapping):
            return decode_predictions(values, expected)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise QuickMLError(f"predictions must be a list, got {type(values).__name__}")
    if len(values) != expected:
        raise QuickMLError(f"expected {expected} predictions, got {len(values)}")

    out = np.array([_scalar(item) for item in values], dtype=float)
    if not np.isfinite(out).all():
        raise QuickMLError("response contains non-finite predictions")
    return out


def _scalar(item: Any) -> float:
    if isinstance(item, Mapping):
        if TARGET in item:
            item = item[TARGET]
        elif len(item) == 1:
            item = next(iter(item.values()))
        else:
            raise QuickMLError(f"cannot identify prediction in {item}")
    try:
        return float(item)
    except (TypeError, ValueError) as exc:
        raise QuickMLError(f"non-numeric prediction: {item!r}") from exc


def _json_number(value: Any) -> float | int:
    if isinstance(value, (np.integer, int)):
        return int(value)
    number = float(value)
    if not math.isfinite(number):
        raise QuickMLError("feature vector contains non-finite values")
    return number


class QuickMLClient:
    def __init__(self, settings: QuickMLSettings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self._session = session or requests.Session()

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """Predict every row, batching to respect the endpoint's payload limit."""
        if features.empty:
            return np.empty(0, dtype=float)
        size = max(1, self.settings.batch_size)
        parts = [
            self._predict_batch(features.iloc[start : start + size])
            for start in range(0, len(features), size)
        ]
        return np.concatenate(parts)

    def _predict_batch(self, batch: pd.DataFrame) -> np.ndarray:
        return decode_predictions(self._post(encode_batch(batch)), expected=len(batch))

    def _post(self, payload: dict[str, Any]) -> Any:
        settings = self.settings
        last_error: str = "no attempt made"
        for attempt in range(settings.max_retries + 1):
            if attempt:
                time.sleep(settings.backoff_s * 2 ** (attempt - 1))
            try:
                response = self._session.post(
                    settings.endpoint_url,
                    json=payload,
                    headers=settings.headers(),
                    timeout=settings.timeout_s,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code in RETRYABLE_STATUS:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                continue
            if not response.ok:
                raise QuickMLError(f"HTTP {response.status_code}: {response.text[:300]}")
            try:
                return response.json()
            except ValueError as exc:
                raise QuickMLError(f"endpoint returned non-JSON body: {response.text[:200]}") from exc
        raise QuickMLError(f"endpoint unavailable after {settings.max_retries + 1} attempts ({last_error})")
