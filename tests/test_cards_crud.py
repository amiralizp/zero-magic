"""Tests for the cards API contracts and CRUD endpoints.

Written from ``specs/card-01-cards-api.md``; every acceptance criterion has at
least one test here or in ``test_stage_machine.py``.
"""

from __future__ import annotations

import pytest

from tests.helpers import (
    AGENT,
    HUMAN,
    HUMAN2,
    card_payload,
    create_card,
    headers,
    move,
)


def test_create_card_returns_typed_public_shape(client):
    response = client.post(
        "/api/v1/cards", headers=headers(HUMAN), json=card_payload()
    )
    assert response.status_code == 201
    body = response.json()

    assert body["id"].startswith("card_")
    assert body["stage"] == "spec"
    assert body["version"] == 1
    assert body["source"] == "manual"
    assert body["prd_id"] is None
    assert body["assignee"] is None
    assert body["created_by"] == {
        "id": HUMAN,
        "display_name": "Ada (human)",
        "role": "human",
    }
    assert body["acceptance_criteria"][0].startswith("POST ")
    # Internal guardrail fields must not leak.
    assert "built_by" not in body
    assert "history" not in body


def test_create_requires_a_known_actor(client):
    missing = client.post("/api/v1/cards", json=card_payload())
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "missing_actor"

    unknown = client.post(
        "/api/v1/cards",
        headers={"X-Actor-Id": "agent:superuser"},
        json=card_payload(),
    )
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "unknown_actor"
    assert unknown.headers["www-authenticate"] == "Actor"


def test_an_agent_cannot_create_a_card(client):
    response = client.post(
        "/api/v1/cards", headers=headers(AGENT), json=card_payload()
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_only"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "ab", "goal": "long enough goal", "acceptance_criteria": ["x"]},
        {"title": "Valid title", "goal": "short", "acceptance_criteria": ["x"]},
        {"title": "Valid title", "goal": "long enough goal", "acceptance_criteria": []},
        {
            "title": "Valid title",
            "goal": "long enough goal",
            "acceptance_criteria": [f"criterion {index}" for index in range(6)],
        },
        {
            "title": "Valid title",
            "goal": "long enough goal",
            "acceptance_criteria": ["same", "same"],
        },
        {
            "title": "   ",
            "goal": "long enough goal",
            "acceptance_criteria": ["criterion"],
        },
        {**card_payload(), "unexpected": True},
    ],
)
def test_invalid_create_payload_returns_422_with_one_error_shape(client, payload):
    response = client.post("/api/v1/cards", headers=headers(HUMAN), json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_payload"
    assert isinstance(error["details"], list)
    assert all("location" in item for item in error["details"])


def test_unknown_assignee_is_a_reference_error(client):
    response = client.post(
        "/api/v1/cards",
        headers=headers(HUMAN),
        json=card_payload(assignee_id="human:nobody"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_assignee"


def test_list_filters_search_and_pagination(client):
    first = create_card(client, title="Add comments")
    second = create_card(client, title="Assign one owner")
    third = create_card(client, title="Export the board")

    move(client, first["id"], "ready", actor=HUMAN)

    ready = client.get("/api/v1/cards", params={"stage": "ready"}).json()
    assert ready["total"] == 1
    assert ready["items"][0]["id"] == first["id"]

    search = client.get("/api/v1/cards", params={"q": "export"}).json()
    assert search["total"] == 1
    assert search["items"][0]["id"] == third["id"]

    page = client.get("/api/v1/cards", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert len(page["items"]) == 1

    # offset past the end is an empty page, not an error.
    empty = client.get("/api/v1/cards", params={"offset": 99}).json()
    assert empty["items"] == []
    assert empty["total"] == 3


def test_list_assignee_filter(client):
    card = create_card(client)
    response = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": HUMAN2},
    )
    assert response.status_code == 200

    mine = client.get("/api/v1/cards", params={"assignee": HUMAN2}).json()
    assert mine["total"] == 1
    assert mine["items"][0]["assignee"]["id"] == HUMAN2

    nobody = client.get("/api/v1/cards", params={"assignee": HUMAN}).json()
    assert nobody["total"] == 0


def test_read_missing_card_is_404(client):
    response = client.get("/api/v1/cards/card_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_not_found"


def test_patch_edits_a_spec_and_bumps_version(client):
    card = create_card(client)
    response = client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=headers(HUMAN),
        json={
            "title": "Add threaded comments",
            "acceptance_criteria": ["A reply returns 201 and names its parent."],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Add threaded comments"
    assert body["version"] == 2
    assert body["goal"] == card["goal"]


def test_patch_is_locked_once_the_card_leaves_spec(client):
    card = create_card(client)
    move(client, card["id"], "ready")
    response = client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=headers(HUMAN),
        json={"goal": "A different goal that is long enough."},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "spec_locked"


def test_agent_cannot_edit_a_spec(client):
    card = create_card(client)
    response = client.patch(
        f"/api/v1/cards/{card['id']}",
        headers=headers(AGENT),
        json={"goal": "Agents must not rewrite the approved work."},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_only"


def test_delete_card_and_comments(client):
    card = create_card(client)
    comment = client.post(
        f"/api/v1/cards/{card['id']}/comments",
        headers=headers(HUMAN2),
        json={"body": "Please add a regression test."},
    )
    assert comment.status_code == 201

    deleted = client.delete(f"/api/v1/cards/{card['id']}", headers=headers(HUMAN))
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"/api/v1/cards/{card['id']}").status_code == 404
    assert (
        client.get(f"/api/v1/cards/{card['id']}/comments").status_code == 404
    )


def test_agent_cannot_delete_a_card(client):
    card = create_card(client)
    response = client.delete(
        f"/api/v1/cards/{card['id']}", headers=headers(AGENT)
    )
    assert response.status_code == 403
    assert client.get(f"/api/v1/cards/{card['id']}").status_code == 200
