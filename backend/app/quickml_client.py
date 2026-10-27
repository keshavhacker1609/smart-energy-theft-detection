"""HTTP client for the published QuickML regression endpoint.

Wire format, as implemented by zcatalyst_sdk.quick_ml.QuickML.predict:

    POST https://api.catalyst.zoho.<dc>/quickml/v1/project/<project_id>/endpoints/predict
    Authorization: Zoho-oauthtoken <access token>
    X-QUICKML-ENDPOINT-KEY: <endpoint key>
    CATALYST-ORG: <org id>                      (optional)
    Environment: Development | Production
    {"data": {"<feature>": <value>, ...}}       one row per request

Access tokens are minted from a Zoho self-client refresh token and renewed on
expiry, so predict.py keeps working beyond the one-hour token lifetime. Rows
are sent concurrently because the endpoint scores a single row per call.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import requests

from app.features import TARGET

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
PREDICTION_KEYS = ("predictions", "prediction", "predicted_value", "result", "results", "data", "output")
TOKEN_REFRESH_MARGIN_S = 120.0
DEFAULT_ACCOUNTS_URL = "https://accounts.zoho.com"


class QuickMLError(RuntimeError):
    """The endpoint could not produce a valid prediction for every row."""


@dataclass(frozen=True)
class OAuthCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    accounts_url: str = DEFAULT_ACCOUNTS_URL


@dataclass(frozen=True)
class QuickMLSettings:
    endpoint_url: str
    endpoint_key: str
    access_token: str | None = None
    oauth: OAuthCredentials | None = None
    org_id: str | None = None
    environment: str = "Development"
    timeout_s: float = 15.0
    max_retries: int = 3
    backoff_s: float = 0.5
    max_workers: int = 16

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> QuickMLSettings:
        env = os.environ if env is None else env

        def get(name: str) -> str:
            return env.get(name, "").strip()

        url, key = get("QUICKML_ENDPOINT_URL"), get("QUICKML_ENDPOINT_KEY")
        if not url:
            raise QuickMLError("QUICKML_ENDPOINT_URL is not set")
        if not key:
            raise QuickMLError("QUICKML_ENDPOINT_KEY is not set")

        oauth_values = (get("ZOHO_CLIENT_ID"), get("ZOHO_CLIENT_SECRET"), get("ZOHO_REFRESH_TOKEN"))
        oauth = None
        if all(oauth_values):
            oauth = OAuthCredentials(
                *oauth_values, accounts_url=get("ZOHO_ACCOUNTS_URL") or DEFAULT_ACCOUNTS_URL
            )
        elif any(oauth_values):
            raise QuickMLError(
                "set all of ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN, or none"
            )

        access_token = get("QUICKML_ACCESS_TOKEN") or None
        if oauth is None and access_token is None:
            raise QuickMLError(
                "no QuickML credentials: set ZOHO_* refresh-token variables or QUICKML_ACCESS_TOKEN"
            )

        return cls(
            endpoint_url=url,
            endpoint_key=key,
            access_token=access_token,
            oauth=oauth,
            org_id=get("CATALYST_ORG_ID") or None,
            environment=get("CATALYST_ENVIRONMENT") or cls.environment,
            timeout_s=float(get("QUICKML_TIMEOUT_S") or cls.timeout_s),
            max_retries=int(get("QUICKML_MAX_RETRIES") or cls.max_retries),
            backoff_s=float(get("QUICKML_BACKOFF_S") or cls.backoff_s),
            max_workers=int(get("QUICKML_MAX_WORKERS") or cls.max_workers),
        )


class TokenSource:
    """Hands out a valid access token, refreshing it shortly before expiry."""

    def __init__(self, settings: QuickMLSettings, session: requests.Session) -> None:
        self._settings = settings
        self._session = session
        self._lock = threading.Lock()
        self._token: str | None = settings.access_token if settings.oauth is None else None
        self._expires_at = math.inf

    def get(self) -> str:
        with self._lock:
            if self._token is None or time.monotonic() >= self._expires_at:
                self._refresh()
            assert self._token is not None
            return self._token

    def invalidate(self) -> bool:
        """Drop the cached token; returns False when it cannot be renewed."""
        if self._settings.oauth is None:
            return False
        with self._lock:
            self._token = None
        return True

    def _refresh(self) -> None:
        oauth = self._settings.oauth
        if oauth is None:
            raise QuickMLError("access token rejected and no refresh credentials are configured")
        try:
            response = self._session.post(
                f"{oauth.accounts_url.rstrip('/')}/oauth/v2/token",
                params={
                    "grant_type": "refresh_token",
                    "client_id": oauth.client_id,
                    "client_secret": oauth.client_secret,
                    "refresh_token": oauth.refresh_token,
                },
                timeout=self._settings.timeout_s,
            )
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise QuickMLError(f"could not refresh Zoho access token: {exc}") from exc
        token = body.get("access_token") if isinstance(body, Mapping) else None
        if not response.ok or not token:
            error = (
                body.get("error", response.status_code) if isinstance(body, Mapping) else response.status_code
            )
            raise QuickMLError(f"Zoho token refresh failed: {error}")
        self._token = str(token)
        lifetime = float(body.get("expires_in", 3600))
        self._expires_at = time.monotonic() + max(0.0, lifetime - TOKEN_REFRESH_MARGIN_S)


def encode_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {"data": {str(column): _json_number(value) for column, value in row.items()}}


def decode_prediction(body: Any) -> float:
    """Extract the single prediction from an endpoint response."""
    value = body
    for _ in range(4):
        if isinstance(value, Mapping):
            key = next((k for k in (TARGET, *PREDICTION_KEYS) if k in value), None)
            if key is None:
                if len(value) == 1:
                    key = next(iter(value))
                else:
                    raise QuickMLError(f"response has no prediction field; keys: {sorted(value)}")
            value = value[key]
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if len(value) != 1:
                raise QuickMLError(f"expected one prediction, got {len(value)}")
            value = value[0]
        else:
            break
    try:
        prediction = float(value)
    except (TypeError, ValueError) as exc:
        raise QuickMLError(f"non-numeric prediction: {value!r}") from exc
    if not math.isfinite(prediction):
        raise QuickMLError("endpoint returned a non-finite prediction")
    return prediction


def _json_number(value: Any) -> float | int:
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    number = float(value)
    if not math.isfinite(number):
        raise QuickMLError("feature vector contains non-finite values")
    return number


class QuickMLClient:
    def __init__(self, settings: QuickMLSettings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self._session = session or requests.Session()
        self._tokens = TokenSource(settings, self._session)

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """One prediction per feature row, in row order."""
        rows = features.to_dict(orient="records")
        if not rows:
            return np.empty(0, dtype=float)
        workers = max(1, min(self.settings.max_workers, len(rows)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return np.fromiter(pool.map(self.predict_row, rows), dtype=float, count=len(rows))

    def predict_row(self, row: Mapping[str, Any]) -> float:
        return decode_prediction(self._post(encode_row(row)))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Zoho-oauthtoken {self._tokens.get()}",
            "X-QUICKML-ENDPOINT-KEY": self.settings.endpoint_key,
            "Environment": self.settings.environment,
        }
        if self.settings.org_id:
            headers["CATALYST-ORG"] = self.settings.org_id
        return headers

    def _post(self, payload: dict[str, Any]) -> Any:
        settings = self.settings
        last_error = "no attempt made"
        token_renewed = False
        attempt = 0
        while attempt <= settings.max_retries:
            if attempt:
                time.sleep(settings.backoff_s * 2 ** (attempt - 1))
            attempt += 1
            try:
                response = self._session.post(
                    settings.endpoint_url, json=payload, headers=self._headers(), timeout=settings.timeout_s
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code == 401 and not token_renewed and self._tokens.invalidate():
                token_renewed = True
                attempt -= 1
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
