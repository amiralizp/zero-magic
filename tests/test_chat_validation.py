"""Validation tests for chat completion parameters (S8.5a).

These tests assert that invalid chat parameters are rejected with 422
instead of crashing with 500. They must fail against the current code
(manual coercion) and pass after the strict schema is introduced.
"""

from __future__ import annotations

from tests.helpers import make_client


def _post(client, body):
    return client.post("/api/v1/chat/completions", json=body)


def test_temperature_string_returns_422():
    client = make_client(chat_api_key="test-key")
    response = _post(
        client,
        {"messages": [{"role": "user", "content": "hi"}], "temperature": "abc"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_max_tokens_string_returns_422():
    client = make_client(chat_api_key="test-key")
    response = _post(
        client,
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": "abc"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_temperature_out_of_range_returns_422():
    client = make_client(chat_api_key="test-key")
    response = _post(
        client,
        {"messages": [{"role": "user", "content": "hi"}], "temperature": 5},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_max_tokens_zero_returns_422():
    client = make_client(chat_api_key="test-key")
    response = _post(
        client,
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 0},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_max_tokens_negative_returns_422():
    client = make_client(chat_api_key="test-key")
    response = _post(
        client,
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": -1},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_unknown_extra_field_returns_422():
    client = make_client(chat_api_key="test-key")
    response = _post(
        client,
        {"messages": [{"role": "user", "content": "hi"}], "unknown_field": "x"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"
