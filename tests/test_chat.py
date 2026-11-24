"""The chat endpoints: contract, key handling and stream framing.

No test touches a real provider. The client is replaced where a successful
upstream call is needed, so a missing key, a broken body and a quota error are
all exercised deterministically.
"""

from __future__ import annotations

import json

import httpx

from app.api import chat as chat_api
from app.ai.chat.client import ChatAuthError

import tests.helpers as helpers


def _events(response: httpx.Response) -> list[dict]:
    frames = []
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload == "[DONE]":
            continue
        frames.append(json.loads(payload))
    return frames


def test_models_requires_a_key():
    client = helpers.make_client()
    response = client.get("/api/v1/chat/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_chat_key"


def test_completions_requires_a_key():
    client = helpers.make_client()
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_chat_key"


def test_completions_rejects_broken_json():
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"


def test_completions_rejects_empty_messages():
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post("/api/v1/chat/completions", json={"messages": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_messages"


def test_client_sends_a_session_and_a_separate_models_url():
    from app.ai.chat.client import ChatClient
    from app.config import Settings

    client = ChatClient(
        Settings(
            chat_api_key="test-key",
            chat_base_url="https://opencode.ai/inference/go/openai/v1",
            chat_models_url="https://opencode.ai/inference/go/v1/models",
            chat_session="ses_gantry",
        )
    )
    assert client.models_url == "https://opencode.ai/inference/go/v1/models"
    assert client.headers["x-opencode-session"] == "ses_gantry"
    assert "x-opencode-session" not in ChatClient(Settings(chat_api_key="test-key")).headers


def test_models_returns_the_provider_list(monkeypatch):
    async def fake_list_models(self) -> list[str]:
        return ["deepseek-flash", "deepseek-v4-pro"]

    monkeypatch.setattr(chat_api.ChatClient, "list_models", fake_list_models)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.get("/api/v1/chat/models")
    assert response.status_code == 200
    assert response.json() == {
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "default": "deepseek-flash",
    }


def test_models_reports_a_rejected_key(monkeypatch):
    async def fake_list_models(self) -> list[str]:
        raise ChatAuthError("nope")

    monkeypatch.setattr(chat_api.ChatClient, "list_models", fake_list_models)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.get("/api/v1/chat/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "chat_key_rejected"


def test_completions_streams_deltas(monkeypatch):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        assert messages[-1] == {"role": "user", "content": "hi"}
        assert messages[0]["role"] == "system"
        assert tools
        return {"role": "assistant", "content": "hello world"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = "".join(
        frame["choices"][0]["delta"]["content"]
        for frame in _events(response)
        if "choices" in frame
    )
    assert text == "hello world"
    assert response.text.rstrip().endswith("data: [DONE]")


def test_completions_explains_a_quota_error(monkeypatch):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        from app.ai.chat.errors import ChatUpstreamError
        raise ChatUpstreamError(status=402, kind="http_status", detail="refused")

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    frames = _events(response)
    assert len(frames) == 1
    assert "balance" in frames[0]["error"]


def test_completions_explains_a_rate_limit(monkeypatch):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        from app.ai.chat.errors import ChatUpstreamError
        raise ChatUpstreamError(status=429, kind="http_status", detail="limited")

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    frames = _events(response)
    assert response.status_code == 200
    assert "rate-limited" in frames[0]["error"]


def test_chat_error_stream_never_leaks_raw_exception_text(monkeypatch):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        raise Exception("upstream failed token=sk-live-abc123 from 10.0.0.7")

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 200
    body = response.text
    assert "sk-live-abc123" not in body
    assert "10.0.0.7" not in body
    assert "token=" not in body
    frames = _events(response)
    assert len(frames) == 1
    assert "error" in frames[0]


def test_chat_creates_a_spec_as_the_signed_in_human(monkeypatch):
    calls = {"n": 0}

    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "create_spec",
                            "arguments": json.dumps(
                                {
                                    "title": "Add a ping",
                                    "goal": "Prove the assistant can create a spec.",
                                    "acceptance_criteria": ["A card exists in Spec."],
                                }
                            ),
                        },
                    }
                ],
            }
        assert any(item.get("role") == "tool" for item in messages)
        return {"role": "assistant", "content": "Created the spec."}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "make a spec for ping"}]},
    )
    frames = _events(response)
    tool = next(frame["gantry_tool"] for frame in frames if "gantry_tool" in frame)
    assert tool["ok"] is True
    assert tool["name"] == "create_spec"
    text = "".join(frame["choices"][0]["delta"]["content"] for frame in frames if "choices" in frame)
    assert text == "Created the spec."

    cards = client.get("/api/v1/cards").json()["items"]
    assert any(card["title"] == "Add a ping" and card["stage"] == "spec" for card in cards)


def test_chat_rejects_an_actor_claim_in_the_body():
    client = helpers.make_client(chat_api_key="test-key")
    for claimed in (helpers.HUMAN, "human:nobody"):
        response = client.post(
            "/api/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "actor": claimed},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_payload"
        assert "unknown_actor" not in response.text


def test_chat_creates_a_spec_even_when_the_model_only_asks_questions(monkeypatch):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        return {"role": "assistant", "content": "Tell me more about the card first."}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "برام یه کارت جدید بساز"}]},
    )
    frames = _events(response)
    tool = next(frame["gantry_tool"] for frame in frames if "gantry_tool" in frame)
    assert tool["ok"] is True
    assert tool["name"] == "create_spec"
    assert len(client.get("/api/v1/cards").json()["items"]) == 1


def test_chat_cannot_bypass_human_only(monkeypatch):
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        if any(item.get("role") == "tool" for item in messages):
            return {"role": "assistant", "content": "The server refused."}
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "create_spec",
                        "arguments": json.dumps(
                            {
                                "title": "Should not exist",
                                "goal": "An agent must not be able to create this.",
                                "acceptance_criteria": ["It is not stored."],
                            }
                        ),
                    },
                }
            ],
        }

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.AGENT),
        json={"messages": [{"role": "user", "content": "create a spec"}]},
    )
    frames = _events(response)
    tool = next(frame["gantry_tool"] for frame in frames if "gantry_tool" in frame)
    assert tool["ok"] is False
    assert tool["code"] == "human_only"
    assert client.get("/api/v1/cards").json()["items"] == []
