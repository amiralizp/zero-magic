"""Test helpers. Plain functions, imported explicitly."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.actors import SEED_ACTORS
from app.config import Settings
from app.main import create_app
from app.schemas.actors import Actor
from app.services.auth import bootstrap_users, issue_token

HUMAN = "human:ada"
HUMAN2 = "human:grace"
HUMAN3 = "human:linus"
AGENT = "agent:builder"
REVIEWER = "agent:reviewer"

# Fixture-only values. They are not real credentials and never reach .env.
TEST_JWT_SECRET = "test-only-jwt-secret-with-at-least-32-chars"
TEST_HUMAN_PASSWORD = "test-human-password-not-a-secret"
TEST_AGENT_PASSWORD = "test-agent-password-not-a-secret"
TEST_TOKEN_TTL_SECONDS = 3600

SAMPLE_PRD = """# Card comments

Users need a way to discuss a card without leaving the board.

- Add comments to every card with a body and an author.
- Reject empty comments with HTTP 422 and an error code.
- List comments oldest first.
- Let both humans and agents add comments.
"""


def actor_for(actor_id: str) -> Actor:
    for actor in SEED_ACTORS:
        if actor.id == actor_id:
            return actor
    raise KeyError(f"unknown seeded actor: {actor_id!r}")


def token_for(actor: str = HUMAN) -> str:
    """Mint a real signed token for a seeded actor, using the test secret."""

    identity = actor_for(actor)
    return issue_token(
        actor_id=identity.id,
        username=identity.id.split(":", 1)[1],
        role=identity.role,
        secret=TEST_JWT_SECRET,
        ttl_seconds=TEST_TOKEN_TTL_SECONDS,
    )


def headers(actor: str = HUMAN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(actor)}"}


class AuthenticatedTestClient(TestClient):
    """A TestClient that always sends a valid token and ignores X-Actor-Id.

    Tests that need to probe missing or invalid tokens use ``make_client(auth=False)``
    or ``raw_client(app)`` so the missing header is not silently repaired.
    """

    def __init__(self, app: FastAPI, *, actor: str = HUMAN, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        self.default_actor = actor

    def request(self, method: str, url: Any, *, headers: Any = None, **kwargs: Any):
        merged = {
            str(key): str(value)
            for key, value in dict(headers or {}).items()
            if str(key).lower() != "x-actor-id"
        }
        if not any(key.lower() == "authorization" for key in merged):
            merged["Authorization"] = f"Bearer {token_for(self.default_actor)}"
        return super().request(method, url, headers=merged, **kwargs)


def raw_client(app: FastAPI) -> TestClient:
    """A plain client for identity-negative tests; no header is injected."""

    return TestClient(app)


def seed_test_users(store: Any) -> None:
    bootstrap_users(
        store,
        human_password=TEST_HUMAN_PASSWORD,
        agent_password=TEST_AGENT_PASSWORD,
    )


def build_test_app(
    *,
    providers: Mapping[str, Any] | None = None,
    **settings_overrides: Any,
) -> FastAPI:
    """Build an isolated app with token settings and the two fixture users."""

    options: dict[str, Any] = {
        "jwt_secret": TEST_JWT_SECRET,
        "token_ttl_seconds": TEST_TOKEN_TTL_SECONDS,
    }
    options.update(settings_overrides)
    settings = Settings(**options)
    app = create_app(settings=settings, provider_overrides=providers)
    seed_test_users(app.state.store)
    return app


def make_client(
    *,
    auth: bool = True,
    actor: str = HUMAN,
    providers: Mapping[str, Any] | None = None,
    **settings_overrides: Any,
) -> TestClient:
    """Build an app with tighter limits or a failing provider for one test.

    ``auth=False`` returns a raw client so a test can assert 401 for a missing
    or invalid token without the wrapper adding one.
    """

    app = build_test_app(providers=providers, **settings_overrides)
    if auth:
        return AuthenticatedTestClient(app, actor=actor)
    return TestClient(app)


def card_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Add comments to cards",
        "goal": "Let people discuss a card where the work happens.",
        "acceptance_criteria": [
            "POST /api/v1/cards/{id}/comments returns 201 with the new comment.",
            "An empty comment returns 422 with error code invalid_payload.",
        ],
        "out_of_scope": ["Editing comments"],
    }
    payload.update(overrides)
    return payload


def create_card(
    client: TestClient, *, actor: str = HUMAN, **overrides: Any
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/cards", headers=headers(actor), json=card_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def move(
    client: TestClient, card_id: str, to_stage: str, *, actor: str = HUMAN
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/cards/{card_id}/transition",
        headers=headers(actor),
        json={"to_stage": to_stage},
    )
    assert response.status_code == 200, response.text
    return response.json()


def advance_to(client: TestClient, card_id: str, stage: str) -> dict[str, Any]:
    """Walk the happy path: human approves, builder builds, human validates."""

    path = [
        ("ready", HUMAN),
        ("building", AGENT),
        ("checks", AGENT),
        ("validation", HUMAN),
        ("done", HUMAN2),
    ]
    current = client.get(f"/api/v1/cards/{card_id}").json()
    for target, actor in path:
        if current["stage"] == stage:
            break
        current = move(client, card_id, target, actor=actor)
    assert current["stage"] == stage or stage not in {"ready", "building", "checks", "validation", "done"}
    return current


def create_prd(
    client: TestClient,
    *,
    actor: str = HUMAN,
    title: str = "Card comments",
    body: str = SAMPLE_PRD,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/prds",
        headers=headers(actor),
        json={"title": title, "body": body},
    )
    assert response.status_code == 201, response.text
    return response.json()


def breakdown(
    client: TestClient,
    prd_id: str,
    *,
    actor: str = HUMAN,
    prompt_version: str = "v2",
    model: str | None = None,
) -> Any:
    payload: dict[str, Any] = {"prompt_version": prompt_version}
    if model is not None:
        payload["model"] = model
    return client.post(
        f"/api/v1/prds/{prd_id}/breakdown",
        headers=headers(actor),
        json=payload,
    )
