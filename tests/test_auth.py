"""S12 HTTP: identity comes only from a signed token, never from a header or body."""

from __future__ import annotations

import pytest

from app.schemas.actors import ActorRole
from app.schemas.chat import ChatCompletionRequest
from app.services.auth import issue_token

from tests.helpers import (
    AGENT,
    HUMAN,
    TEST_AGENT_PASSWORD,
    TEST_HUMAN_PASSWORD,
    TEST_JWT_SECRET,
    TEST_TOKEN_TTL_SECONDS,
    headers,
    make_client,
    raw_client,
    token_for,
)


def _login(client, username: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_human_login_returns_a_signed_token():
    client = make_client(auth=False)
    response = _login(client, "ada", TEST_HUMAN_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"].count(".") == 2


def test_agent_login_returns_a_signed_token():
    client = make_client(auth=False)
    response = _login(client, "builder", TEST_AGENT_PASSWORD)
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("ada", "wrong-password"),
        ("builder", TEST_HUMAN_PASSWORD),
        ("nobody", TEST_HUMAN_PASSWORD),
    ],
)
def test_bad_credentials_are_a_generic_401(username, password):
    client = make_client(auth=False)
    response = _login(client, username, password)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.headers["www-authenticate"] == "Bearer"


def test_login_token_works_on_a_protected_route():
    anonymous = make_client(auth=False)
    token = _login(anonymous, "ada", TEST_HUMAN_PASSWORD).json()["access_token"]
    response = anonymous.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["actor_id"] == HUMAN


def test_x_actor_id_does_not_identify_a_caller():
    client = make_client(auth=False)
    response = client.post(
        "/api/v1/cards",
        headers={"X-Actor-Id": HUMAN},
        json={
            "title": "No token",
            "goal": "The header must be ignored.",
            "acceptance_criteria": ["A token is required."],
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"
    assert "missing_actor" not in response.text


def test_a_valid_token_overrides_a_forged_header():
    client = make_client(auth=False)
    response = client.post(
        "/api/v1/cards",
        headers={**headers(HUMAN), "X-Actor-Id": AGENT},
        json={
            "title": "Signed in as Ada",
            "goal": "The forged header must not change the caller.",
            "acceptance_criteria": ["The card is created by the human."],
        },
    )
    assert response.status_code == 201
    assert response.json()["created_by"]["id"] == HUMAN
    assert response.json()["created_by"]["role"] == "human"


def test_me_reports_the_token_identity():
    client = make_client()
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["actor_id"] == HUMAN
    assert body["username"] == "ada"
    assert body["role"] == "human"


def test_malformed_authorization_header_is_401():
    client = make_client(auth=False)
    response = client.get("/api/v1/cards", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/actors",
        "/api/v1/meta",
        "/api/v1/cards",
        "/api/v1/prds",
        "/api/v1/chat/models",
        "/api/v1/auth/me",
    ],
)
def test_get_endpoints_need_a_token_except_health(path):
    client = make_client(auth=False)
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_health_stays_public():
    client = make_client(auth=False)
    assert client.get("/api/v1/health").status_code == 200


def test_chat_body_cannot_claim_an_actor():
    assert "actor" not in ChatCompletionRequest.model_fields
    client = make_client(chat_api_key="test-key")
    response = client.post(
        "/api/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "actor": HUMAN},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_tokens_are_bound_to_a_signed_in_user():
    client = make_client(auth=False)
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_for(AGENT)}"}
    )
    assert response.status_code == 200
    assert response.json()["actor_id"] == AGENT
    assert response.json()["role"] == "agent"


@pytest.mark.parametrize(
    ("actor_id", "username", "claimed_role"),
    [
        (HUMAN, "ada", ActorRole.AGENT),
        (AGENT, "builder", ActorRole.HUMAN),
    ],
)
def test_token_role_must_match_the_stored_actor_role(actor_id, username, claimed_role):
    client = make_client(auth=False)
    forged = issue_token(
        actor_id=actor_id,
        username=username,
        role=claimed_role,
        secret=TEST_JWT_SECRET,
        ttl_seconds=TEST_TOKEN_TTL_SECONDS,
    )
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert response.headers["www-authenticate"] == "Bearer"


def test_raw_client_helper_does_not_add_a_token():
    app = make_client().app
    assert raw_client(app).get("/api/v1/cards").status_code == 401
