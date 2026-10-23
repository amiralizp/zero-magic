"""Test helpers. Plain functions, imported explicitly."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

HUMAN = "human:ada"
HUMAN2 = "human:grace"
HUMAN3 = "human:linus"
AGENT = "agent:builder"
REVIEWER = "agent:reviewer"

SAMPLE_PRD = """# Card comments

Users need a way to discuss a card without leaving the board.

- Add comments to every card with a body and an author.
- Reject empty comments with HTTP 422 and an error code.
- List comments oldest first.
- Let both humans and agents add comments.
"""


def headers(actor: str = HUMAN) -> dict[str, str]:
    return {"X-Actor-Id": actor}


def make_client(
    *,
    providers: Mapping[str, Any] | None = None,
    **settings_overrides: Any,
) -> TestClient:
    """Build an app with tighter limits or a failing provider for one test."""

    settings = Settings(**settings_overrides)
    return TestClient(
        create_app(settings=settings, provider_overrides=providers)
    )


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
