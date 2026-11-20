"""S13: authorization lives in services, not only in HTTP dependencies."""

from __future__ import annotations

import pytest

from app.domain_errors import AppError
from app.schemas.cards import CardCreate, Stage, TransitionRequest
from app.services import cards as cards_service

from tests.helpers import (
    AGENT,
    HUMAN,
    HUMAN2,
    actor_for,
    advance_to,
    card_payload,
    create_card,
    headers,
    make_client,
)


def _unmark_validation_to_done(monkeypatch) -> None:
    """Remove the edge from the human-only list without changing the matrix."""

    monkeypatch.setattr(
        cards_service,
        "HUMAN_ONLY_TRANSITIONS",
        cards_service.HUMAN_ONLY_TRANSITIONS - {(Stage.VALIDATION, Stage.DONE)},
    )


def test_create_card_service_checks_the_role_without_any_http_gate():
    store = make_client().app.state.store
    with pytest.raises(AppError) as error:
        cards_service.create_card(
            store, actor_for(AGENT), CardCreate(**card_payload())
        )
    assert error.value.status_code == 403
    assert error.value.code == "human_only"


def test_create_card_service_still_allows_a_human():
    store = make_client().app.state.store
    record = cards_service.create_card(
        store, actor_for(HUMAN), CardCreate(**card_payload())
    )
    assert record.created_by == HUMAN


def test_agent_cannot_reach_done_if_the_edge_is_not_human_only(client, monkeypatch):
    _unmark_validation_to_done(monkeypatch)
    card = create_card(client)
    advance_to(client, card["id"], "validation")

    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(AGENT),
        json={"to_stage": "done"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "agent_not_allowed"


def test_transition_service_blocks_agent_to_done_without_http(monkeypatch):
    _unmark_validation_to_done(monkeypatch)
    client = make_client()
    store = client.app.state.store
    card = create_card(client)
    advance_to(client, card["id"], "validation")

    with pytest.raises(AppError) as error:
        cards_service.transition_card(
            store,
            actor_for(AGENT),
            card["id"],
            TransitionRequest(to_stage=Stage.DONE),
        )
    assert error.value.status_code == 403
    assert error.value.code == "agent_not_allowed"
    assert store.get_card(card["id"]).stage is Stage.VALIDATION


def test_human_can_still_reach_done_if_the_edge_is_not_human_only(client, monkeypatch):
    _unmark_validation_to_done(monkeypatch)
    card = create_card(client)
    advance_to(client, card["id"], "validation")

    response = client.post(
        f"/api/v1/cards/{card['id']}/transition",
        headers=headers(HUMAN2),
        json={"to_stage": "done"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == "done"
