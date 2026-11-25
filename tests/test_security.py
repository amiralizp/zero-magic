"""S14: one security matrix for every protected operation.

The table below is checked against OpenAPI, so a new route cannot silently
escape the 401/403 contracts. Public routes (health, login, docs, console) are
listed explicitly and are deliberately outside the matrix.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import jwt
import pytest

from app.api import chat as chat_api
from app.schemas.actors import ActorRole
from app.services.auth import ALGORITHM, ISSUER, issue_token

from tests.helpers import (
    AGENT,
    HUMAN,
    HUMAN2,
    SAMPLE_PRD,
    TEST_HUMAN_PASSWORD,
    TEST_JWT_SECRET,
    TEST_TOKEN_TTL_SECONDS,
    card_payload,
    create_card,
    create_prd,
    headers,
    make_client,
    move,
)


@dataclass(frozen=True)
class RouteCase:
    """A protected operation plus a recipe for a valid request."""

    name: str
    method: str
    path: str
    build: Callable[[Any], tuple[str, dict[str, Any]]]
    human_status: int
    agent_code: str | None = None


def _get_card(client: Any) -> tuple[str, dict[str, Any]]:
    card = create_card(client)
    return f"/api/v1/cards/{card['id']}", {}


def _patch_card(client: Any) -> tuple[str, dict[str, Any]]:
    card = create_card(client)
    return f"/api/v1/cards/{card['id']}", {"json": {"title": "Renamed card"}}


def _transition_card(client: Any) -> tuple[str, dict[str, Any]]:
    card = create_card(client)
    for target, actor in (
        ("ready", HUMAN),
        ("building", AGENT),
        ("checks", AGENT),
        ("validation", HUMAN),
    ):
        move(client, card["id"], target, actor=actor)
    return f"/api/v1/cards/{card['id']}/transition", {"json": {"to_stage": "done"}}


def _get_comments(client: Any) -> tuple[str, dict[str, Any]]:
    card = create_card(client)
    return f"/api/v1/cards/{card['id']}/comments", {}


def _post_comment(client: Any) -> tuple[str, dict[str, Any]]:
    card = create_card(client)
    return f"/api/v1/cards/{card['id']}/comments", {"json": {"body": "A comment."}}


def _put_assignee(client: Any) -> tuple[str, dict[str, Any]]:
    card = create_card(client)
    return f"/api/v1/cards/{card['id']}/assignee", {"json": {"assignee_id": HUMAN2}}


def _get_prd(client: Any) -> tuple[str, dict[str, Any]]:
    prd = create_prd(client)
    return f"/api/v1/prds/{prd['id']}", {}


def _post_breakdown(client: Any) -> tuple[str, dict[str, Any]]:
    prd = create_prd(client)
    return f"/api/v1/prds/{prd['id']}/breakdown", {"json": {"prompt_version": "v2"}}


def _post_chat_confirm(client: Any) -> tuple[str, dict[str, Any]]:
    from app.services import chat_proposals

    card = create_card(client)
    args = {"card": card["id"]}
    signed = chat_proposals.issue_proposal(
        jwt_secret=client.app.state.settings.jwt_secret,
        actor_id=HUMAN,
        tool="delete_card",
        arguments=args,
    )
    client.app.state.chat_proposals.put(
        chat_proposals.PendingProposal(
            proposal_id=signed["proposal_id"],
            actor_id=HUMAN,
            tool="delete_card",
            arguments=args,
            exp=signed["exp"],
        )
    )
    return "/api/v1/chat/confirm", {"json": {"token": signed["token"], "arguments": args}}


PROTECTED = (
    RouteCase("get-actors", "GET", "/api/v1/actors", lambda c: ("/api/v1/actors", {}), 200),
    RouteCase("get-meta", "GET", "/api/v1/meta", lambda c: ("/api/v1/meta", {}), 200),
    RouteCase("get-me", "GET", "/api/v1/auth/me", lambda c: ("/api/v1/auth/me", {}), 200),
    RouteCase(
        "post-cards",
        "POST",
        "/api/v1/cards",
        lambda c: ("/api/v1/cards", {"json": card_payload()}),
        201,
        "human_only",
    ),
    RouteCase("get-cards", "GET", "/api/v1/cards", lambda c: ("/api/v1/cards", {}), 200),
    RouteCase("get-card", "GET", "/api/v1/cards/{card_id}", _get_card, 200),
    RouteCase("patch-card", "PATCH", "/api/v1/cards/{card_id}", _patch_card, 200, "human_only"),
    RouteCase("delete-card", "DELETE", "/api/v1/cards/{card_id}", _get_card, 204, "human_only"),
    RouteCase(
        "transition-to-done",
        "POST",
        "/api/v1/cards/{card_id}/transition",
        _transition_card,
        200,
        "agent_not_allowed",
    ),
    RouteCase("get-comments", "GET", "/api/v1/cards/{card_id}/comments", _get_comments, 200),
    RouteCase("post-comments", "POST", "/api/v1/cards/{card_id}/comments", _post_comment, 201),
    RouteCase("put-assignee", "PUT", "/api/v1/cards/{card_id}/assignee", _put_assignee, 200, "human_only"),
    RouteCase(
        "post-prds",
        "POST",
        "/api/v1/prds",
        lambda c: ("/api/v1/prds", {"json": {"title": "Card comments", "body": SAMPLE_PRD}}),
        201,
        "human_only",
    ),
    RouteCase("get-prds", "GET", "/api/v1/prds", lambda c: ("/api/v1/prds", {}), 200),
    RouteCase("get-prd", "GET", "/api/v1/prds/{prd_id}", _get_prd, 200),
    RouteCase("post-breakdown", "POST", "/api/v1/prds/{prd_id}/breakdown", _post_breakdown, 201, "human_only"),
    RouteCase("get-chat-models", "GET", "/api/v1/chat/models", lambda c: ("/api/v1/chat/models", {}), 200),
    RouteCase(
        "post-chat-completions",
        "POST",
        "/api/v1/chat/completions",
        lambda c: (
            "/api/v1/chat/completions",
            {"json": {"messages": [{"role": "user", "content": "hi"}]}},
        ),
        200,
    ),
    RouteCase(
        "post-chat-confirm",
        "POST",
        "/api/v1/chat/confirm",
        _post_chat_confirm,
        200,
        "forbidden",
    ),
)


def _signed_token(**overrides: Any) -> str:
    options: dict[str, Any] = {
        "actor_id": HUMAN,
        "username": "ada",
        "role": ActorRole.HUMAN,
        "secret": TEST_JWT_SECRET,
        "ttl_seconds": TEST_TOKEN_TTL_SECONDS,
    }
    options.update(overrides)
    return issue_token(**options)


def _garbage_token() -> str:
    return "not-a-signed-token"


def _expired_token() -> str:
    return _signed_token(ttl_seconds=-60)


def _wrong_signature_token() -> str:
    return _signed_token(secret="a-different-secret-with-at-least-32-chars")


def _unknown_actor_token() -> str:
    return _signed_token(actor_id="human:nobody", username="nobody")


def _wrong_role_token() -> str:
    return _signed_token(role=ActorRole.AGENT)


def _unknown_role_token() -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": ISSUER,
        "sub": HUMAN,
        "username": "ada",
        "role": "admin",
        "iat": now,
        "nbf": now,
        "exp": now + TEST_TOKEN_TTL_SECONDS,
    }
    return jwt.encode(claims, TEST_JWT_SECRET, algorithm=ALGORITHM)


INVALID_TOKENS = (
    pytest.param(_garbage_token, id="garbage"),
    pytest.param(_expired_token, id="expired"),
    pytest.param(_wrong_signature_token, id="wrong-signature"),
    pytest.param(_unknown_actor_token, id="unknown-actor"),
    pytest.param(_wrong_role_token, id="wrong-role"),
    pytest.param(_unknown_role_token, id="unknown-role"),
)


@pytest.fixture
def security_client(monkeypatch: Any) -> Any:
    """A raw client with a chat key and offline chat providers."""

    async def fake_list_models(self: Any) -> list[str]:
        return ["mock-model"]

    async def fake_complete(
        self: Any,
        messages: Any,
        model: Any = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        tools: Any = None,
    ) -> dict[str, str]:
        return {"role": "assistant", "content": "ok"}

    monkeypatch.setattr(chat_api.ChatClient, "list_models", fake_list_models)
    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    return make_client(auth=False, chat_api_key="test-key")


def test_security_table_covers_every_protected_operation(security_client: Any) -> None:
    spec = security_client.get("/openapi.json").json()
    public = {("get", "/api/v1/health"), ("post", "/api/v1/auth/login")}
    actual = {
        (method.lower(), path)
        for path, operations in spec["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    } - public
    listed = {(case.method.lower(), case.path) for case in PROTECTED}
    assert listed == actual


@pytest.mark.parametrize("case", PROTECTED, ids=lambda case: case.name)
def test_protected_route_without_a_token_is_401(security_client: Any, case: RouteCase) -> None:
    path, kwargs = case.build(security_client)
    response = security_client.request(case.method, path, **kwargs)
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "missing_token"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("token_factory", INVALID_TOKENS)
@pytest.mark.parametrize("case", PROTECTED, ids=lambda case: case.name)
def test_protected_route_with_a_bad_token_is_401(
    security_client: Any, case: RouteCase, token_factory: Callable[[], str]
) -> None:
    path, kwargs = case.build(security_client)
    response = security_client.request(
        case.method,
        path,
        headers={"Authorization": f"Bearer {token_factory()}"},
        **kwargs,
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "invalid_token"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "case", [case for case in PROTECTED if case.agent_code], ids=lambda case: case.name
)
def test_agent_cannot_use_human_only_routes(security_client: Any, case: RouteCase) -> None:
    assert case.agent_code is not None
    path, kwargs = case.build(security_client)
    response = security_client.request(
        case.method, path, headers=headers(AGENT), **kwargs
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == case.agent_code


@pytest.mark.parametrize("case", PROTECTED, ids=lambda case: case.name)
def test_human_can_use_every_protected_route(security_client: Any, case: RouteCase) -> None:
    path, kwargs = case.build(security_client)
    response = security_client.request(
        case.method, path, headers=headers(HUMAN), **kwargs
    )
    assert response.status_code == case.human_status, response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/backup"),
        ("GET", "/api/v1/admin"),
        ("POST", "/api/v1/admin/backup"),
        ("POST", "/api/v1/ops/backup"),
    ],
)
def test_removed_admin_routes_are_absent(security_client: Any, method: str, path: str) -> None:
    response = security_client.request(method, path, headers=headers(HUMAN), json={})
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


def test_openapi_has_no_backup_or_admin_routes(security_client: Any) -> None:
    paths = security_client.get("/openapi.json").json()["paths"]
    assert not any(
        "backup" in path or "admin" in path for path in paths
    ), paths.keys()


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/api/v1/health", {}),
        (
            "POST",
            "/api/v1/auth/login",
            {"json": {"username": "ada", "password": TEST_HUMAN_PASSWORD}},
        ),
        ("GET", "/openapi.json", {}),
        ("GET", "/docs", {}),
        ("GET", "/redoc", {}),
        ("GET", "/", {}),
        ("GET", "/console", {}),
        ("GET", "/chat", {}),
    ],
)
def test_public_routes_stay_public(
    security_client: Any, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    response = security_client.request(method, path, **kwargs)
    assert response.status_code != 401, response.text
