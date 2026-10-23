"""The stage machine: legal edges, human-only edges, and the builder guardrail.

Every rule in this file exists because the funnel's whole promise is that a
card cannot skip review, and an agent cannot approve its own work.
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
    move,
)


def test_happy_path_walks_every_stage(client):
    card = create_card(client)
    assert card["stage"] == "spec"

    ready = move(client, card["id"], "ready", actor=HUMAN)
    assert ready["stage"] == "ready"

    building = move(client, card["id"], "building", actor=AGENT)
    assert building["stage"] == "building"
    # The builder is recorded and, with no assignee, becomes the assignee.
    assert building["assignee"]["id"] == AGENT

    checks = move(client, card["id"], "checks", actor=AGENT)
    assert checks["stage"] == "checks"

    validation = move(client, card["id"], "validation", actor=HUMAN)
    assert validation["stage"] == "validation"

    done = move(client, card["id"], "done", actor=HUMAN2)
    assert done["stage"] == "done"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("spec", "building"),
        ("spec", "checks"),
        ("spec", "done"),
        ("ready", "checks"),
        ("ready", "validation"),
        ("building", "ready"),
        ("building", "validation"),
        ("checks", "done"),
        ("validation", "checks"),
    ],
)
def test_edges_outside_the_matrix_return_409(client, source, target):
    card = create_card(client)
    if source != "spec":
        advance_to(client, card["id"], source)

    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(HUMAN),
        json={"to_stage": target},
    )
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "illegal_transition"
    assert error["details"]["requested_stage"] == target


def test_moving_to_the_current_stage_is_409(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(HUMAN),
        json={"to_stage": "spec"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "illegal_transition"


def test_done_is_terminal(client):
    card = create_card(client)
    advance_to(client, card["id"], "done")

    for target in ("spec", "ready", "building", "checks", "validation", "done"):
        response = client.post(
            f"/api/v1/cards/{card['id']}/transition",
            headers=headers(HUMAN),
            json={"to_stage": target},
        )
        assert response.status_code == 409


def test_unknown_transition_target_is_422(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(HUMAN),
        json={"to_stage": "shipped"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_transition_payload_rejects_extra_fields(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(HUMAN),
        json={"to_stage": "ready", "force": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("spec", "ready"),
        ("ready", "spec"),
        ("checks", "validation"),
        ("checks", "building"),
        ("validation", "building"),
        ("validation", "done"),
    ],
)
def test_agents_cannot_take_human_only_edges(client, source, target):
    card = create_card(client)
    if source != "spec":
        advance_to(client, card["id"], source)

    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(AGENT),
        json={"to_stage": target},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "agent_not_allowed"


def test_builder_cannot_validate_its_own_card(client):
    card = create_card(client, title="Built by a human")
    # A human walks the card itself, so built_by is that human.
    for target in ("ready", "building", "checks", "validation"):
        move(client, card["id"], target, actor=HUMAN)

    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(HUMAN),
        json={"to_stage": "done"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_validation_blocked"

    # A different human may validate it.
    accepted = move(client, card["id"], "done", actor=HUMAN2)
    assert accepted["stage"] == "done"


def test_agent_that_built_the_card_still_cannot_validate_it(client):
    card = create_card(client)
    advance_to(client, card["id"], "validation")

    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(AGENT),
        json={"to_stage": "done"},
    )
    # The edge is human-only, so the actor guard fires before self-validation.
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "agent_not_allowed"


def test_transition_missing_actor_is_401(client):
    card = create_card(client)
    response = client.post(
        f"/api/v1/cards/{card['id']}/transition", json={"to_stage": "ready"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_actor"


def test_transition_on_missing_card_is_404(client):
    response = client.post(
        "/api/v1/cards/card_missing/transition",
        headers=headers(HUMAN),
        json={"to_stage": "ready"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_not_found"


def test_transition_note_is_stored_in_the_audit_log(client, app):
    card = create_card(client)
    client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(HUMAN),
        json={"to_stage": "ready", "note": "Spec reviewed by Ada."},
    )
    entries = [
        entry
        for entry in app.state.store.audit_log
        if entry["event"] == "card.transitioned"
    ]
    assert entries[-1]["actor_id"] == HUMAN
    assert entries[-1]["extra"]["note"] == "Spec reviewed by Ada."
