from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
import requests

from app.quickml_client import (
    OAuthCredentials,
    QuickMLClient,
    QuickMLError,
    QuickMLSettings,
    decode_prediction,
    encode_row,
)

URL = "https://api.catalyst.zoho.com/quickml/v1/project/1/endpoints/predict"
TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
FEATURES = pd.DataFrame({"h_01": [1, 0, 0], "cdd": [0.0, 1.5, 3.0]})


def _response(status: int, body: Any) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = status < 400
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    response.text = str(body)
    return response


class FakeSession:
    """Routes POSTs to the token endpoint or the model endpoint."""

    def __init__(self, predictions: list[Any], tokens: list[Any] | None = None) -> None:
        self.predictions = list(predictions)
        self.tokens = list(tokens or [])
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        queue = self.tokens if url == TOKEN_URL else self.predictions
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def model_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["url"] == URL]


def _client(session: FakeSession, **overrides: Any) -> QuickMLClient:
    settings = QuickMLSettings(
        endpoint_url=URL,
        endpoint_key="ek",
        access_token=overrides.pop("access_token", "static-token"),
        backoff_s=0.0,
        max_workers=1,
        **overrides,
    )
    return QuickMLClient(settings, session=session)  # type: ignore[arg-type]


def test_encode_row_uses_sdk_shape_and_plain_numbers() -> None:
    payload = encode_row({"h_01": np.int8(1), "cdd": np.float64(1.5)})
    assert payload == {"data": {"h_01": 1, "cdd": 1.5}}
    assert type(payload["data"]["h_01"]) is int


def test_encode_row_rejects_non_finite() -> None:
    with pytest.raises(QuickMLError, match="non-finite"):
        encode_row({"cdd": float("nan")})


@pytest.mark.parametrize(
    "body",
    [
        123.4,
        "123.4",
        {"prediction": 123.4},
        {"predictions": [123.4]},
        {"status": "success", "data": {"predicted_value": "123.4"}},
        {"data": [{"target_demand_kw": 123.4}]},
        {"result": {"value": 123.4}},
    ],
)
def test_decode_accepts_supported_shapes(body: Any) -> None:
    assert decode_prediction(body) == pytest.approx(123.4)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"status": "ok", "message": "fine"}, "no prediction field"),
        ({"predictions": [1.0, 2.0]}, "expected one prediction"),
        ({"prediction": "abc"}, "non-numeric"),
        ({"prediction": float("inf")}, "non-finite"),
        (None, "non-numeric"),
    ],
)
def test_decode_rejects_invalid_bodies(body: Any, message: str) -> None:
    with pytest.raises(QuickMLError, match=message):
        decode_prediction(body)


def test_predict_sends_one_row_per_request_in_order() -> None:
    session = FakeSession([_response(200, {"prediction": v}) for v in (10, 20, 30)])
    np.testing.assert_allclose(_client(session).predict(FEATURES), [10, 20, 30])
    calls = session.model_calls()
    assert [c["json"]["data"]["cdd"] for c in calls] == [0.0, 1.5, 3.0]
    headers = calls[0]["headers"]
    assert headers["Authorization"] == "Zoho-oauthtoken static-token"
    assert headers["X-QUICKML-ENDPOINT-KEY"] == "ek"
    assert headers["Environment"] == "Development"
    assert "CATALYST-ORG" not in headers


def test_concurrent_predictions_keep_row_order() -> None:
    session = MagicMock()
    session.post.side_effect = lambda url, json, **_: _response(200, {"prediction": json["data"]["cdd"] * 10})
    settings = QuickMLSettings(endpoint_url=URL, endpoint_key="ek", access_token="t", max_workers=4)
    client = QuickMLClient(settings, session=session)
    features = pd.DataFrame({"cdd": np.arange(50, dtype=float)})
    np.testing.assert_allclose(client.predict(features), np.arange(50) * 10)


def test_org_header_is_sent_when_configured() -> None:
    session = FakeSession([_response(200, {"prediction": 1})])
    _client(session, org_id="777").predict(FEATURES.iloc[:1])
    assert session.model_calls()[0]["headers"]["CATALYST-ORG"] == "777"


def test_retries_transient_failures_then_succeeds() -> None:
    session = FakeSession(
        [requests.ConnectionError("reset"), _response(503, "busy"), _response(200, {"prediction": 5})]
    )
    np.testing.assert_allclose(_client(session).predict(FEATURES.iloc[:1]), [5])
    assert len(session.model_calls()) == 3


def test_gives_up_after_max_retries() -> None:
    session = FakeSession([requests.Timeout("slow")] * 3)
    with pytest.raises(QuickMLError, match="after 3 attempts"):
        _client(session, max_retries=2).predict(FEATURES.iloc[:1])


@pytest.mark.parametrize(("status", "body"), [(400, "bad row"), (403, "forbidden"), (401, "expired")])
def test_client_errors_are_not_retried(status: int, body: str) -> None:
    session = FakeSession([_response(status, body)])
    with pytest.raises(QuickMLError, match=f"HTTP {status}"):
        _client(session).predict(FEATURES.iloc[:1])
    assert len(session.model_calls()) == 1


def test_non_json_body_is_an_error() -> None:
    session = FakeSession([_response(200, ValueError("not json"))])
    with pytest.raises(QuickMLError, match="non-JSON"):
        _client(session).predict(FEATURES.iloc[:1])


def test_empty_input_makes_no_request() -> None:
    session = FakeSession([])
    assert _client(session).predict(FEATURES.iloc[:0]).shape == (0,)
    assert session.calls == []


def _oauth_client(session: FakeSession) -> QuickMLClient:
    return _client(session, access_token=None, oauth=OAuthCredentials("cid", "secret", "refresh"))


def test_refresh_token_is_exchanged_once_and_cached() -> None:
    session = FakeSession(
        [_response(200, {"prediction": 1}), _response(200, {"prediction": 2})],
        tokens=[_response(200, {"access_token": "fresh", "expires_in": 3600})],
    )
    _oauth_client(session).predict(FEATURES.iloc[:2])
    token_calls = [c for c in session.calls if c["url"] == TOKEN_URL]
    assert len(token_calls) == 1
    assert token_calls[0]["params"]["grant_type"] == "refresh_token"
    assert session.model_calls()[1]["headers"]["Authorization"] == "Zoho-oauthtoken fresh"


def test_expired_token_is_refreshed_on_401() -> None:
    session = FakeSession(
        [_response(401, "expired"), _response(200, {"prediction": 7})],
        tokens=[
            _response(200, {"access_token": "first", "expires_in": 3600}),
            _response(200, {"access_token": "second", "expires_in": 3600}),
        ],
    )
    np.testing.assert_allclose(_oauth_client(session).predict(FEATURES.iloc[:1]), [7])
    assert session.model_calls()[1]["headers"]["Authorization"] == "Zoho-oauthtoken second"


def test_token_refresh_failure_is_reported() -> None:
    session = FakeSession([], tokens=[_response(400, {"error": "invalid_code"})])
    with pytest.raises(QuickMLError, match="invalid_code"):
        _oauth_client(session).predict(FEATURES.iloc[:1])


def test_token_endpoint_unreachable_is_reported() -> None:
    session = FakeSession([], tokens=[requests.ConnectionError("dns")])
    with pytest.raises(QuickMLError, match="could not refresh"):
        _oauth_client(session).predict(FEATURES.iloc[:1])


def test_settings_from_env() -> None:
    settings = QuickMLSettings.from_env(
        {
            "QUICKML_ENDPOINT_URL": URL,
            "QUICKML_ENDPOINT_KEY": "ek",
            "ZOHO_CLIENT_ID": "cid",
            "ZOHO_CLIENT_SECRET": "secret",
            "ZOHO_REFRESH_TOKEN": "refresh",
            "ZOHO_ACCOUNTS_URL": "https://accounts.zoho.in",
            "CATALYST_ORG_ID": "777",
            "CATALYST_ENVIRONMENT": "Production",
            "QUICKML_MAX_WORKERS": "4",
        }
    )
    assert settings.oauth == OAuthCredentials("cid", "secret", "refresh", "https://accounts.zoho.in")
    assert settings.org_id == "777" and settings.max_workers == 4
    assert settings.environment == "Production"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "QUICKML_ENDPOINT_URL is not set"),
        ({"QUICKML_ENDPOINT_URL": URL}, "QUICKML_ENDPOINT_KEY is not set"),
        ({"QUICKML_ENDPOINT_URL": URL, "QUICKML_ENDPOINT_KEY": "k"}, "no QuickML credentials"),
        ({"QUICKML_ENDPOINT_URL": URL, "QUICKML_ENDPOINT_KEY": "k", "ZOHO_CLIENT_ID": "c"}, "set all of"),
    ],
)
def test_settings_from_env_rejects_incomplete_config(env: dict[str, str], message: str) -> None:
    with pytest.raises(QuickMLError, match=message):
        QuickMLSettings.from_env(env)
