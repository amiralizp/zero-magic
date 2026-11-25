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
    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        if any(item.get("role") == "tool" for item in messages):
            return {"role": "assistant", "content": "I prepared a proposal for your confirmation."}
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

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "make a spec for ping"}]},
    )
    frames = _events(response)
    proposal = next(frame["gantry_proposal"] for frame in frames if "gantry_proposal" in frame)
    assert proposal["tool"] == "create_spec"
    assert client.get("/api/v1/cards").json()["items"] == []

    confirm = client.post(
        "/api/v1/chat/confirm",
        headers=helpers.headers(helpers.HUMAN),
        json={"token": proposal["token"]},
    )
    assert confirm.status_code == 200
    assert confirm.json()["ok"] is True

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


# Z-1: forced create_spec fallback removed; see test_chat_question_only_answer_creates_no_card.


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
    proposal = next(frame["gantry_proposal"] for frame in frames if "gantry_proposal" in frame)
    confirm = client.post(
        "/api/v1/chat/confirm",
        headers=helpers.headers(helpers.AGENT),
        json={"token": proposal["token"]},
    )
    assert confirm.status_code == 200
    assert confirm.json()["ok"] is False
    assert confirm.json()["code"] == "human_only"
    assert client.get("/api/v1/cards").json()["items"] == []


def test_chat_rejects_oversize_message_and_never_calls_provider(monkeypatch):
    called = {"value": False}

    async def fake_complete(self, *args, **kwargs):  # pragma: no cover - must not run
        called["value"] = True
        return {"role": "assistant", "content": "no"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "x" * (3 * 1024 * 1024)}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"
    assert called["value"] is False


def test_chat_rejects_too_many_messages(monkeypatch):
    called = {"value": False}

    async def fake_complete(self, *args, **kwargs):  # pragma: no cover - must not run
        called["value"] = True
        return {"role": "assistant", "content": "no"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    messages = [{"role": "user", "content": f"m{i}"} for i in range(31)]
    response = client.post("/api/v1/chat/completions", json={"messages": messages})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"
    assert called["value"] is False


def test_chat_rejects_total_message_size(monkeypatch):
    called = {"value": False}

    async def fake_complete(self, *args, **kwargs):  # pragma: no cover - must not run
        called["value"] = True
        return {"role": "assistant", "content": "no"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    # 4 messages * 7000 chars = 28000 > 24000
    messages = [{"role": "user", "content": "y" * 7000} for _ in range(4)]
    response = client.post("/api/v1/chat/completions", json={"messages": messages})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"
    assert called["value"] is False


def test_chat_rate_limit_returns_429_after_limit(monkeypatch):
    async def fake_complete(self, *args, **kwargs):
        return {"role": "assistant", "content": "ok"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key", chat_rate_limit=20)
    headers = helpers.headers(helpers.HUMAN)
    statuses = []
    for _ in range(40):
        response = client.post(
            "/api/v1/chat/completions",
            headers=headers,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        statuses.append(response.status_code)
    assert 429 in statuses
    first_429 = statuses.index(429)
    assert all(s == 200 for s in statuses[:first_429])
    assert all(s == 429 for s in statuses[first_429:])
    limited = client.post(
        "/api/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert limited.headers.get("retry-after")


def test_chat_max_tokens_clamped_to_cap(monkeypatch):
    seen = {}

    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        seen["max_tokens"] = max_tokens
        return {"role": "assistant", "content": "ok"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key", chat_max_tokens_cap=2048)
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 32768},
    )
    assert response.status_code == 200
    assert seen["max_tokens"] == 2048


def test_chat_rejects_model_not_in_allowlist(monkeypatch):
    called = {"value": False}

    async def fake_complete(self, *args, **kwargs):  # pragma: no cover - must not run
        called["value"] = True
        return {"role": "assistant", "content": "no"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(
        chat_api_key="test-key",
        chat_model="deepseek-flash",
        chat_allowed_models="deepseek-flash,deepseek-reasoner",
    )
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "hi"}], "model": "openai/o1-pro"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"
    assert called["value"] is False


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def test_chat_write_tool_returns_proposal_and_does_not_execute(monkeypatch):
    client = helpers.make_client(chat_api_key="test-key")
    created = client.post("/api/v1/cards", headers=helpers.headers(helpers.HUMAN), json=helpers.card_payload())
    assert created.status_code == 201
    card_id = created.json()["id"]

    async def fake_complete(self, *args, **kwargs):
        return {"role": "assistant", "content": None, "tool_calls": [_tool_call("delete_card", {"card": card_id})]}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": f"delete {card_id}"}]},
    )
    assert response.status_code == 200
    frames = _events(response)
    proposals = [f["gantry_proposal"] for f in frames if "gantry_proposal" in f]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["tool"] == "delete_card"
    assert proposal["arguments"]["card"] == card_id
    assert proposal["token"]
    assert proposal["summary"]
    # write not executed
    card = client.get(f"/api/v1/cards/{card_id}")
    assert card.status_code == 200

    confirm = client.post(
        "/api/v1/chat/confirm",
        headers=helpers.headers(helpers.HUMAN),
        json={"token": proposal["token"]},
    )
    assert confirm.status_code == 200
    body = confirm.json()
    assert body["ok"] is True
    gone = client.get(f"/api/v1/cards/{card_id}")
    assert gone.status_code == 404


def test_chat_confirm_rejects_other_actor_tampered_expired_and_replay(monkeypatch):
    client = helpers.make_client(chat_api_key="test-key")
    created = client.post("/api/v1/cards", headers=helpers.headers(helpers.HUMAN), json=helpers.card_payload())
    card_id = created.json()["id"]

    async def fake_delete(self, *args, **kwargs):
        return {"role": "assistant", "content": None, "tool_calls": [_tool_call("delete_card", {"card": card_id})]}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_delete)
    resp = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "delete it"}]},
    )
    proposal = next(f["gantry_proposal"] for f in _events(resp) if "gantry_proposal" in f)
    token = proposal["token"]

    # other actor
    other = client.post("/api/v1/chat/confirm", headers=helpers.headers(helpers.AGENT), json={"token": token})
    assert other.status_code in {401, 403}
    assert client.get(f"/api/v1/cards/{card_id}").status_code == 200

    # tampered argument - confirm with modified arguments should fail
    tampered = dict(proposal)
    tampered_args = dict(proposal["arguments"])
    tampered_args["card"] = "card_does_not_matter"
    tampered_resp = client.post(
        "/api/v1/chat/confirm",
        headers=helpers.headers(helpers.HUMAN),
        json={"token": token, "arguments": tampered_args},
    )
    assert tampered_resp.status_code in {400, 401, 403, 422}
    assert client.get(f"/api/v1/cards/{card_id}").status_code == 200

    # successful confirm
    ok = client.post("/api/v1/chat/confirm", headers=helpers.headers(helpers.HUMAN), json={"token": token})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    # replay
    replay = client.post("/api/v1/chat/confirm", headers=helpers.headers(helpers.HUMAN), json={"token": token})
    assert replay.status_code in {400, 401, 403, 409, 422}
    assert replay.json()["error"]["code"] != "ok"


def test_chat_confirm_rejects_expired_proposal(monkeypatch):
    import app.services.chat_proposals as chat_proposals

    client = helpers.make_client(chat_api_key="test-key")
    created = client.post("/api/v1/cards", headers=helpers.headers(helpers.HUMAN), json=helpers.card_payload())
    card_id = created.json()["id"]

    async def fake_delete(self, *args, **kwargs):
        return {"role": "assistant", "content": None, "tool_calls": [_tool_call("delete_card", {"card": card_id})]}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_delete)
    resp = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "delete it"}]},
    )
    proposal = next(f["gantry_proposal"] for f in _events(resp) if "gantry_proposal" in f)

    # force expiry
    real_now = chat_proposals._now
    monkeypatch.setattr(chat_proposals, "_now", lambda: real_now() + 600)
    expired = client.post(
        "/api/v1/chat/confirm",
        headers=helpers.headers(helpers.HUMAN),
        json={"token": proposal["token"]},
    )
    assert expired.status_code in {400, 401, 403}
    assert client.get(f"/api/v1/cards/{card_id}").status_code == 200


def test_chat_agent_cannot_confirm_human_only_action(monkeypatch):
    client = helpers.make_client(chat_api_key="test-key")

    async def fake_create(self, *args, **kwargs):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("create_spec", {"title": "Agent spec", "goal": "should not be created by agent", "acceptance_criteria": ["no"]})],
        }

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_create)
    resp = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.AGENT),
        json={"messages": [{"role": "user", "content": "create spec"}]},
    )
    proposals = [f["gantry_proposal"] for f in _events(resp) if "gantry_proposal" in f]
    assert proposals
    confirm = client.post(
        "/api/v1/chat/confirm",
        headers=helpers.headers(helpers.AGENT),
        json={"token": proposals[0]["token"]},
    )
    assert confirm.status_code in {200, 403}
    if confirm.status_code == 200:
        assert confirm.json()["ok"] is False
        assert confirm.json()["code"] in {"human_only", "forbidden", "role_forbidden"}
    assert client.get("/api/v1/cards").json()["items"] == []


def test_chat_question_only_answer_creates_no_card(monkeypatch):
    async def fake_complete(self, *args, **kwargs):
        return {"role": "assistant", "content": "What kind of spec do you want?"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = helpers.make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "create a spec for login"}]},
    )
    assert response.status_code == 200
    frames = _events(response)
    assert not any("gantry_tool" in f and f["gantry_tool"].get("name") == "create_spec" and f["gantry_tool"].get("ok") for f in frames)
    assert client.get("/api/v1/cards").json()["items"] == []


def test_chat_proposal_token_and_arguments_never_appear_in_logs(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO)
    client = helpers.make_client(chat_api_key="test-key")
    created = client.post("/api/v1/cards", headers=helpers.headers(helpers.HUMAN), json=helpers.card_payload())
    card_id = created.json()["id"]
    secret_argument = "TOP_SECRET_ARGUMENT_VALUE"

    async def fake_complete(self, *args, **kwargs):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("comment_on_card", {"card": card_id, "body": secret_argument})],
        }

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    response = client.post(
        "/api/v1/chat/completions",
        headers=helpers.headers(helpers.HUMAN),
        json={"messages": [{"role": "user", "content": "comment"}]},
    )
    proposal = next(f["gantry_proposal"] for f in _events(response) if "gantry_proposal" in f)
    token = proposal["token"]
    confirm = client.post(
        "/api/v1/chat/confirm",
        headers=helpers.headers(helpers.HUMAN),
        json={"token": token},
    )
    assert confirm.status_code == 200
    log_text = caplog.text
    assert token not in log_text
    assert secret_argument not in log_text
