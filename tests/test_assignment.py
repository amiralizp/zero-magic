"""Card assignment, built from ``specs/card-03-assignment.md``.

One card, at most one assignee. Assignment is a human decision; an agent can
discover what is assigned to it but cannot assign work.
"""

from __future__ import annotations

import pytest

from tests.helpers import (
    AGENT,
    HUMAN,
    HUMAN2,
    REVIEWER,
    advance_to,
    create_card,
    headers,
    move,
)


def test_assign_and_clear(client):
    card = create_card(client)
    assert card["assignee"] is None

    assigned = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": AGENT},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assignee"]["id"] == AGENT
    assert assigned.json()["version"] == card["version"] + 1

    cleared = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["assignee"] is None


def test_assign_to_a_human(client):
    card = create_card(client)
    response = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": HUMAN2},
    )
    assert response.status_code == 200
    assert response.json()["assignee"]["role"] == "human"


def test_unknown_assignee_is_422(client):
    card = create_card(client)
    response = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": "agent:ghost"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unknown_assignee"
    assert "ghost" in error["message"]


def test_assignee_key_is_required(client):
    card = create_card(client)
    response = client.put(
        f"/api/v1/cards/{card['id']}/assignee", headers=headers(HUMAN), json={}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_agents_cannot_assign(client):
    card = create_card(client)
    response = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(AGENT),
        json={"assignee_id": AGENT},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_only"


def test_assigning_a_missing_card_is_404(client):
    response = client.put(
        "/api/v1/cards/card_missing/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": HUMAN},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_not_found"


def test_done_cards_cannot_be_reassigned(client):
    card = create_card(client)
    advance_to(client, card["id"], "done")
    response = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": HUMAN2},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "card_closed"


def test_create_with_assignee(client):
    card = create_card(client, assignee_id=AGENT)
    assert card["assignee"]["id"] == AGENT
    listed = client.get("/api/v1/cards", params={"assignee": AGENT}).json()
    assert listed["total"] == 1


def test_assignment_filter_composes_with_stage(client):
    first = create_card(client, title="Assigned in spec")
    second = create_card(client, title="Assigned and ready")
    client.put(
        f"/api/v1/cards/{first['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": AGENT},
    )
    client.put(
        f"/api/v1/cards/{second['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": AGENT},
    )
    client.post(
        f"/api/v1/cards/{second['id']}/transition",
        headers=headers(HUMAN),
        json={"to_stage": "ready"},
    )

    both = client.get("/api/v1/cards", params={"assignee": AGENT}).json()
    assert both["total"] == 2
    ready = client.get(
        "/api/v1/cards", params={"assignee": AGENT, "stage": "ready"}
    ).json()
    assert ready["total"] == 1
    assert ready["items"][0]["id"] == second["id"]


@pytest.mark.parametrize("stage", ["spec", "ready", "building", "checks", "validation"])
def test_assignment_is_allowed_until_done(client, stage):
    card = create_card(client)
    advance_to(client, card["id"], stage)
    response = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": HUMAN2},
    )
    assert response.status_code == 200

def test_agent_can_only_work_on_its_own_card(client):
    card = create_card(client)
    move(client, card["id"], "ready", actor=HUMAN)

    assigned = client.put(
        f"/api/v1/cards/{card['id']}/assignee",
        headers=headers(HUMAN),
        json={"assignee_id": REVIEWER},
    )
    assert assigned.status_code == 200

    denied = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(AGENT),
        json={"to_stage": "building"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "not_assignee"

    allowed = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(REVIEWER),
        json={"to_stage": "building"},
    )
    assert allowed.status_code == 200
