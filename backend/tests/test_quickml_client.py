from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
import requests

from app.quickml_client import (
    QuickMLClient,
    QuickMLError,
    QuickMLSettings,
    decode_predictions,
    encode_batch,
)


def _response(status: int, body: Any) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body
    response.text = str(body)
    return response


def _client(responses: list[Any], **overrides: Any) -> tuple[QuickMLClient, MagicMock]:
    session = MagicMock(spec=requests.Session)
    session.post.side_effect = responses
    settings = QuickMLSettings(endpoint_url="https://example.test/predict", backoff_s=0.0, **overrides)
    return QuickMLClient(settings, session=session), session


FEATURES = pd.DataFrame({"h_01": [1, 0, 0], "cdd": [0.0, 1.5, 3.0]})


def test_encode_batch_emits_plain_json_numbers() -> None:
    payload = encode_batch(FEATURES.iloc[:1])
    assert payload == {"data": [{"h_01": 1, "cdd": 0.0}]}
    assert type(payload["data"][0]["h_01"]) is int


@pytest.mark.parametrize(
    "body",
    [
        {"predictions": [1.0, 2.0]},
        {"result": ["1.0", "2"]},
        {"data": {"predictions": [1, 2]}},
        [1.0, 2.0],
        {"predictions": [{"target_demand_kw": 1.0}, {"target_demand_kw": 2.0}]},
        {"predictions": [{"value": 1.0}, {"value": 2.0}]},
    ],
)
def test_decode_accepts_supported_shapes(body: Any) -> None:
    np.testing.assert_allclose(decode_predictions(body, 2), [1.0, 2.0])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"predictions": [1.0]}, "expected 2"),
        ({"status": "ok"}, "no prediction field"),
        ({"predictions": [1.0, "abc"]}, "non-numeric"),
        ({"predictions": [1.0, float("nan")]}, "non-finite"),
        ({"predictions": "1,2"}, "must be a list"),
        ({"predictions": [{"a": 1, "b": 2}, 2.0]}, "cannot identify"),
    ],
)
def test_decode_rejects_invalid_bodies(body: Any, message: str) -> None:
    with pytest.raises(QuickMLError, match=message):
        decode_predictions(body, 2)


def test_predict_batches_and_preserves_order() -> None:
    client, session = _client(
        [_response(200, {"predictions": [10, 20]}), _response(200, {"predictions": [30]})],
        batch_size=2,
    )
    np.testing.assert_allclose(client.predict(FEATURES), [10, 20, 30])
    assert session.post.call_count == 2
    assert len(session.post.call_args_list[1].kwargs["json"]["data"]) == 1


def test_retries_transient_failures_then_succeeds() -> None:
    client, session = _client(
        [
            requests.ConnectionError("reset"),
            _response(503, "busy"),
            _response(200, {"predictions": [1, 2, 3]}),
        ]
    )
    np.testing.assert_allclose(client.predict(FEATURES), [1, 2, 3])
    assert session.post.call_count == 3


def test_gives_up_after_max_retries() -> None:
    client, session = _client([requests.Timeout("slow")] * 3, max_retries=2)
    with pytest.raises(QuickMLError, match="after 3 attempts"):
        client.predict(FEATURES)
    assert session.post.call_count == 3


def test_client_errors_are_not_retried() -> None:
    client, session = _client([_response(401, "bad key")])
    with pytest.raises(QuickMLError, match="HTTP 401"):
        client.predict(FEATURES)
    assert session.post.call_count == 1


def test_empty_input_makes_no_request() -> None:
    client, session = _client([])
    assert client.predict(FEATURES.iloc[:0]).shape == (0,)
    session.post.assert_not_called()


def test_settings_from_env_builds_headers() -> None:
    settings = QuickMLSettings.from_env(
        {
            "QUICKML_ENDPOINT_URL": "https://example.test/predict",
            "QUICKML_API_KEY": "secret",
            "QUICKML_AUTH_SCHEME": "Zoho-oauthtoken",
            "QUICKML_EXTRA_HEADERS": '{"CATALYST-ORG": "123"}',
            "QUICKML_BATCH_SIZE": "50",
        }
    )
    assert settings.batch_size == 50
    headers = settings.headers()
    assert headers["Authorization"] == "Zoho-oauthtoken secret"
    assert headers["CATALYST-ORG"] == "123"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "QUICKML_ENDPOINT_URL is not set"),
        ({"QUICKML_ENDPOINT_URL": "u", "QUICKML_EXTRA_HEADERS": "{bad"}, "not valid JSON"),
        ({"QUICKML_ENDPOINT_URL": "u", "QUICKML_EXTRA_HEADERS": "[1]"}, "JSON object"),
    ],
)
def test_settings_from_env_rejects_bad_config(env: dict[str, str], message: str) -> None:
    with pytest.raises(QuickMLError, match=message):
        QuickMLSettings.from_env(env)
