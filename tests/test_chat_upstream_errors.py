"""Behavior-lock tests for chat upstream failures (S8.8b).

Pin the SSE event sequence for connection errors, timeouts, bad-body
responses and mid-stream failures, so the S8.8b refactor (moving httpx
error handling into the AI layer) cannot change them.
"""

from __future__ import annotations

import httpx

import app.api.chat as chat_api
from app.ai.chat.errors import ChatUpstreamError
from tests.helpers import headers, make_client


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


def _fake(exc):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        raise exc
    return fake_complete


def test_connection_error_yields_error_frame(monkeypatch):
    exc = ChatUpstreamError(status=None, kind="connection", detail="connection refused")
    monkeypatch.setattr(chat_api.ChatClient, "complete", _fake(exc))
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    frames = _events(response)
    assert len(frames) == 1
    assert "error" in frames[0]
    assert isinstance(frames[0]["error"], str)


def test_timeout_yields_error_frame(monkeypatch):
    exc = ChatUpstreamError(status=None, kind="timeout", detail="timed out")
    monkeypatch.setattr(chat_api.ChatClient, "complete", _fake(exc))
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    frames = _events(response)
    assert len(frames) == 1
    assert "error" in frames[0]


def test_500_non_json_body_yields_error_frame(monkeypatch):
    exc = ChatUpstreamError(status=500, kind="http_status", detail="not json at all")
    monkeypatch.setattr(chat_api.ChatClient, "complete", _fake(exc))
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    frames = _events(response)
    assert len(frames) == 1
    assert "error" in frames[0]
    assert "chat_upstream_error" in frames[0]["error"]
    assert "500" not in frames[0]["error"]
    assert "not json at all" not in response.text


def test_stream_fails_after_first_event(monkeypatch):
    calls = {"n": 0}

    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc1",
                        "type": "function",
                        "function": {
                            "name": "create_spec",
                            "arguments": '{"title": "X", "goal": "Y enough text here.", "acceptance_criteria": ["ok"]}',
                        },
                    }
                ],
            }
        from app.ai.chat.errors import ChatUpstreamError
        raise ChatUpstreamError(status=500, kind="http_status", detail="boom")

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        headers=headers(),
        json={"messages": [{"role": "user", "content": "make a card"}]},
    )
    assert response.status_code == 200
    frames = _events(response)
    assert len(frames) >= 2
    assert "gantry_tool" in frames[0]
    assert "error" in frames[-1]


# --- Real client translation tests (exercise app/ai/chat/client.py) ----------


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in for translation tests."""

    def __init__(self, *, response=None, exc=None, timeout=None, transport=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, headers=None):
        if self._exc is not None:
            raise self._exc
        return self._response

    async def post(self, url, headers=None, json=None):
        if self._exc is not None:
            raise self._exc
        return self._response


def _patch_httpx(monkeypatch, *, response=None, exc=None):
    def factory(timeout=None, transport=None):
        return _FakeAsyncClient(response=response, exc=exc, timeout=timeout, transport=transport)
    monkeypatch.setattr("httpx.AsyncClient", factory)


def test_real_client_connection_error_translation(monkeypatch):
    import httpx
    from app.ai.chat.client import ChatClient, ChatUpstreamError
    from app.config import Settings

    settings = Settings(chat_api_key="test-key", chat_base_url="http://example.com")
    client = ChatClient(settings)
    _patch_httpx(monkeypatch, exc=httpx.ConnectError("refused"))

    import asyncio
    async def run():
        try:
            await client.list_models()
        except ChatUpstreamError as e:
            return e
        return None

    err = asyncio.run(run())
    assert err is not None
    assert err.status is None
    assert err.kind == "connection"


def test_real_client_timeout_translation(monkeypatch):
    import httpx
    from app.ai.chat.client import ChatClient, ChatUpstreamError
    from app.config import Settings

    settings = Settings(chat_api_key="test-key", chat_base_url="http://example.com")
    client = ChatClient(settings)
    _patch_httpx(monkeypatch, exc=httpx.ReadTimeout("timed out"))

    import asyncio
    async def run():
        try:
            await client.complete([{"role": "user", "content": "hi"}])
        except ChatUpstreamError as e:
            return e
        return None

    err = asyncio.run(run())
    assert err is not None
    assert err.status is None
    assert err.kind == "timeout"


def test_real_client_500_non_json_translation(monkeypatch):
    import httpx
    from app.ai.chat.client import ChatClient, ChatUpstreamError
    from app.config import Settings

    settings = Settings(chat_api_key="test-key", chat_base_url="http://example.com")
    client = ChatClient(settings)
    resp = httpx.Response(500, text="not json at all", request=httpx.Request("POST", "http://example.com"))
    _patch_httpx(monkeypatch, response=resp)

    import asyncio
    async def run():
        try:
            await client.complete([{"role": "user", "content": "hi"}])
        except ChatUpstreamError as e:
            return e
        return None

    err = asyncio.run(run())
    assert err is not None
    assert err.status == 500
    assert err.kind == "http_status"
    assert "not json at all" in err.detail


def test_real_client_http_status_translation(monkeypatch):
    import httpx
    from app.ai.chat.client import ChatClient, ChatUpstreamError
    from app.config import Settings

    settings = Settings(chat_api_key="test-key", chat_base_url="http://example.com")
    client = ChatClient(settings)

    for status in (401, 402, 403, 429):
        resp = httpx.Response(status, text="boom", request=httpx.Request("POST", "http://example.com"))
        _patch_httpx(monkeypatch, response=resp)

        import asyncio
        async def run():
            try:
                await client.complete([{"role": "user", "content": "hi"}])
            except ChatUpstreamError as e:
                return e
            return None

        err = asyncio.run(run())
        assert err is not None, f"status {status}: no error raised"
        assert err.status == status, f"status {status}: got {err.status}"
        assert err.kind == "http_status", f"status {status}: got {err.kind}"


def test_real_client_translation_removed_fails():
    """Prove the translation is necessary: if client re-raises raw httpx, tests fail."""
    # This test is a manual proof, not an automated one. It is skipped by default.
    import pytest
    pytest.skip("manual proof only")