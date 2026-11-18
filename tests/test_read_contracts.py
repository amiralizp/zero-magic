"""Behavior-lock tests for list and get reads (S8.3).

These tests pin the current behavior of the card and PRD list/get endpoints
so the S8.3 refactor can move the logic into services without changing
responses. They must pass against the current code unchanged.
"""

from __future__ import annotations

from tests.helpers import (
    HUMAN,
    HUMAN2,
    create_card,
    create_prd,
    headers,
    make_client,
)


def _card_keys() -> set[str]:
    return {
        "id",
        "title",
        "goal",
        "acceptance_criteria",
        "out_of_scope",
        "stage",
        "assignee",
        "created_by",
        "prd_id",
        "source",
        "created_at",
        "updated_at",
        "version",
        "depends_on",
    }


def test_list_limit_and_offset_exact_slice(client):
    ids = [create_card(client, title=f"Card {i}")["id"] for i in range(5)]

    page = client.get("/api/v1/cards", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 5
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert [item["id"] for item in page["items"]] == ids[1:3]


def test_list_filter_by_stage(client):
    first = create_card(client, title="Ready card")
    second = create_card(client, title="Spec card")
    from tests.helpers import move

    move(client, first["id"], "ready")

    ready = client.get("/api/v1/cards", params={"stage": "ready"}).json()
    assert ready["total"] == 1
    assert ready["items"][0]["id"] == first["id"]

    spec = client.get("/api/v1/cards", params={"stage": "spec"}).json()
    assert spec["total"] == 1
    assert spec["items"][0]["id"] == second["id"]


def test_list_filter_by_assignee(client):
    card = create_card(client)
    client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": HUMAN2},
    )

    mine = client.get("/api/v1/cards", params={"assignee": HUMAN2}).json()
    assert mine["total"] == 1
    assert mine["items"][0]["id"] == card["id"]

    nobody = client.get("/api/v1/cards", params={"assignee": HUMAN}).json()
    assert nobody["total"] == 0
    assert nobody["items"] == []


def test_get_existing_card_status_and_keys(client):
    card = create_card(client)
    response = client.get(f"/api/v1/cards/{card['id']}")
    assert response.status_code == 200
    assert set(response.json().keys()) == _card_keys()
    assert response.json()["id"] == card["id"]


def test_get_unknown_card_is_404(client):
    response = client.get("/api/v1/cards/card_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_not_found"


def test_prd_list_and_get(client):
    first = create_prd(client, title="First PRD")
    second = create_prd(client, title="Second PRD")

    listed = client.get("/api/v1/prds").json()
    assert listed["total"] == 2
    assert listed["items"][0]["id"] == second["id"]

    read = client.get(f"/api/v1/prds/{first['id']}")
    assert read.status_code == 200
    assert read.json() == first


def test_prd_get_unknown_is_404(client):
    response = client.get("/api/v1/prds/prd_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "prd_not_found"
