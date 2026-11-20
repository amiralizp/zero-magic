"""Card comments, built from ``specs/card-02-comments.md``.

Comments are the only stage-independent write in the API: they must work in
every stage, for humans and agents, and must never mutate the card.
"""

from __future__ import annotations

import pytest

from tests.helpers import (
    AGENT,
    HUMAN,
    HUMAN2,
    advance_to,
    create_card,
    headers,
    raw_client,
)


def test_add_comment_returns_the_typed_comment(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(HUMAN2),
        json={"body": "  Please add a regression test.  "},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("cmt_")
    assert body["card_id"] == card["id"]
    assert body["body"] == "Please add a regression test."
    assert body["author"] == {
        "id": HUMAN2,
        "display_name": "Grace (human)",
        "role": "human",
    }
    assert body["created_at"]


def test_agents_may_comment(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(AGENT),
        json={"body": "Blocked on the migration. Asking for a review."},
    )
    assert response.status_code == 201
    assert response.json()["author"]["role"] == "agent"


@pytest.mark.parametrize("stage", ["spec", "ready", "building", "checks", "validation", "done"])
def test_comments_work_in_every_stage(client, stage):
    card = create_card(client)
    advance_to(client, card["id"], stage)
    response = client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(HUMAN),
        json={"body": f"A note while in {stage}."},
    )
    assert response.status_code == 201, response.text


def test_comments_are_listed_oldest_first(client):
    card = create_card(client)
    bodies = ["First look.", "Second look.", "Third look."]
    for body in bodies:
        created = client.post(
            f"/api/v1/cards/{card['id']}/comments",
            headers=headers(HUMAN),
            json={"body": body},
        )
        assert created.status_code == 201

    response = client.get(f"/api/v1/cards/{card['id']}/comments")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [item["body"] for item in payload["items"]] == bodies


def test_empty_comment_is_422(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(HUMAN),
        json={"body": "    "},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_oversized_comment_is_422(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(HUMAN),
        json={"body": "x" * 2001},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_comment_requires_a_token(client):
    card = create_card(client)
    response = raw_client(client.app).post(
        f"/api/v1/cards/{card['id']}/comments", json={"body": "Hello"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_comment_on_missing_card_is_404(client):
    missing = client.post(
        "/api/v1/cards/card_missing/comments",
        headers=headers(HUMAN),
        json={"body": "Hello"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "card_not_found"

    listed = client.get(
        "/api/v1/cards/card_missing/comments", headers=headers(HUMAN)
    )
    assert listed.status_code == 404
    assert listed.json()["error"]["code"] == "card_not_found"


def test_commenting_does_not_mutate_the_card(client):
    card = create_card(client)
    client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(HUMAN),
        json={"body": "No change expected."},
    )
    reread = client.get(f"/api/v1/cards/{card['id']}").json()
    assert reread["version"] == card["version"]
    assert reread["updated_at"] == card["updated_at"]


def test_unicode_comment_round_trips(client):
    card = create_card(client)
    body = "لطفاً تست بازگشتی اضافه کنید. ✅"
    created = client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(HUMAN),
        json={"body": body},
    )
    assert created.status_code == 201
    assert created.json()["body"] == body
    listed = client.get(f"/api/v1/cards/{card['id']}/comments").json()
    assert listed["items"][0]["body"] == body
