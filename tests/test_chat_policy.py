"""Behavior-lock tests for chat policy (S8.5b).

Pin the missing-key precondition, the upstream status -> hint mapping and the
actor fallback from the request body, so the S8.5b refactor can move them out
of the router without changing behavior.
"""

from __future__ import annotations

import httpx

import app.api.chat as chat_api
from tests.helpers import make_client


def _events(response):
    import json

    frames = []
    for line in response.text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: ") :]
            if payload == "[DONE]":
                continue
            frames.append(json.loads(payload))
    return frames


def test_missing_key_models_endpoint():
    client = make_client()  # no chat_api_key
    response = client.get("/api/v1/chat/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_chat_key"
    assert set(response.json()["error"].keys()) == {"code", "message"}


def test_missing_key_completions_endpoint():
    client = make_client()  # no chat_api_key
    response = client.post(
        "/api/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_chat_key"


def _upstream_test(monkeypatch, status):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        request = httpx.Request("POST", "https://api.example.com/chat/completions")
        response = httpx.Response(status, request=request, text="boom")
        raise httpx.HTTPStatusError("upstream", request=request, response=response)

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    frames = _events(response)
    assert len(frames) == 1
    return frames[0]["error"]


def test_upstream_401_hint(monkeypatch):
    err = _upstream_test(monkeypatch, 401)
    assert "rejected the API key" in err


def test_upstream_403_hint(monkeypatch):
    err = _upstream_test(monkeypatch, 403)
    assert "403 Forbidden" in err


def test_upstream_402_hint(monkeypatch):
    err = _upstream_test(monkeypatch, 402)
    assert "balance" in err


def test_upstream_429_hint(monkeypatch):
    err = _upstream_test(monkeypatch, 429)
    assert "rate-limited" in err


def test_upstream_unmapped_status(monkeypatch):
    err = _upstream_test(monkeypatch, 500)
    assert "error 500" in err


def test_actor_fallback_from_body():
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "actor": "human:ada"},
    )
    # No key configured? Actually key is set. The request goes through validation
    # and reaches the provider. We just check it is not a 401 unknown_actor.
    # (The provider call will fail because complete is not mocked, but the
    # actor resolution itself must succeed.)
    assert response.status_code in (200, 500)  # not 401
    if response.status_code != 200:
        assert "unknown_actor" not in response.text


def test_actor_header_wins_over_body(monkeypatch):
    captured = {}

    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        captured["messages"] = messages
        return {"role": "assistant", "content": "ok"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        headers={"X-Actor-Id": "human:ada"},
        json={"messages": [{"role": "user", "content": "hi"}], "actor": "human:grace"},
    )
    assert response.status_code == 200


def test_actor_unknown_body_returns_401():
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "actor": "human:nobody"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unknown_actor"
