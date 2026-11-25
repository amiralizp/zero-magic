"""Behavior-lock tests for presenter output (S8.7).

Pin the exact JSON of breakdown cards and chat tool results so the S8.7
refactor (services stop importing presenters) cannot change them.
"""

from __future__ import annotations

import json

from app.services.chat_agent import execute_tool

from tests.helpers import (
    HUMAN,
    SAMPLE_PRD,
    create_prd,
    headers,
    make_client,
)


def _normalise_card(card: dict) -> dict:
    """Strip ids and timestamps, keeping everything else."""
    out = dict(card)
    for key in ("id", "created_at", "updated_at"):
        out.pop(key, None)
    return out


def test_breakdown_card_shape_is_stable(client):
    prd = create_prd(client)
    response = client.post(
        f"/api/v1/prds/{prd['id']}/breakdown",
        headers=headers(HUMAN),
        json={"prompt_version": "v2"},
    )
    assert response.status_code == 201
    body = response.json()
    cards = body["cards"]
    assert len(cards) == 5

    # Full top-level keys of the breakdown response.
    assert set(body.keys()) == {
        "prd_id",
        "cards",
        "model_used",
        "fallback_used",
        "prompt_version",
        "attempts",
        "usage",
        "duration_ms",
        "warnings",
    }

    # Full dict of the first card (normalise ids and timestamps).
    first = _normalise_card(cards[0])
    assert set(first.keys()) == {
        "title",
        "goal",
        "acceptance_criteria",
        "out_of_scope",
        "stage",
        "assignee",
        "created_by",
        "depends_on",
        "prd_id",
        "version",
        "source",
    }
    assert first["stage"] == "spec"
    assert first["prd_id"] == prd["id"]
    assert first["source"] == "prd"
    assert first["created_by"]["id"] == HUMAN
    assert first["acceptance_criteria"]
    assert first["out_of_scope"] == []

    # Normalise and compare against a re-fetched card.
    for card in cards:
        fetched = client.get(f"/api/v1/cards/{card['id']}").json()
        assert _normalise_card(fetched) == _normalise_card(card), (
            f"GET card differs from breakdown card: {card['id']}"
        )


def test_chat_tool_result_card_shape(monkeypatch):
    import app.api.chat as chat_api

    calls = {"n": 0}

    async def fake_complete(self, messages, model=None, temperature=0.7, max_tokens=2048, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc1",
                        "type": "function",
                        "function": {
                            "name": "create_spec",
                            "arguments": json.dumps(
                                {
                                    "title": "Chat-created card",
                                    "goal": "Verify the tool result shape is stable.",
                                    "acceptance_criteria": ["It works."],
                                }
                            ),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr(chat_api.ChatClient, "complete", fake_complete)
    client = make_client(chat_api_key="test-key")
    client.post(
        "/api/v1/prds",
        headers=headers(HUMAN),
        json={"title": "P", "body": SAMPLE_PRD},
    )
    response = client.post(
        "/api/v1/chat/completions",
        headers=headers(HUMAN),
        json={"messages": [{"role": "user", "content": "make a card"}]},
    )
    assert response.status_code == 200
    frames = []
    for line in response.text.splitlines():
        if line.startswith("data: ") and line[6:] != "[DONE]":
            frames.append(json.loads(line[6:]))
    proposal = next(f["gantry_proposal"] for f in frames if "gantry_proposal" in f)
    confirm = client.post(
        "/api/v1/chat/confirm",
        headers=headers(HUMAN),
        json={"token": proposal["token"]},
    )
    assert confirm.status_code == 200
    cards = client.get("/api/v1/cards").json()["items"]
    assert any(c["title"] == "Chat-created card" for c in cards)


def _store(client):
    return client.app.state.store


def test_create_spec_tool_result_card():
    client = make_client()
    store = _store(client)
    ada = store.get_actor("human:ada")
    created = execute_tool(
        store,
        ada,
        "create_spec",
        {
            "title": "Tool card",
            "goal": "Verify the create_spec tool result card shape.",
            "acceptance_criteria": ["It works."],
        },
    )
    assert created["ok"] is True
    card = created["card"]
    assert set(card.keys()) == {"id", "title", "stage", "goal", "acceptance_criteria", "assignee"}
    assert card["title"] == "Tool card"
    assert card["stage"] == "spec"
    assert card["goal"] == "Verify the create_spec tool result card shape."
    assert card["acceptance_criteria"] == ["It works."]
    assert card["assignee"] is None
    assert card["id"].startswith("card_")


def test_update_spec_tool_result_card():
    client = make_client()
    store = _store(client)
    ada = store.get_actor("human:ada")
    created = execute_tool(
        store,
        ada,
        "create_spec",
        {
            "title": "Updatable card",
            "goal": "Verify the update_spec tool result card shape.",
            "acceptance_criteria": ["It works."],
        },
    )
    assert created["ok"] is True

    updated = execute_tool(
        store,
        ada,
        "update_spec",
        {"card": "Updatable card", "goal": "Updated goal for shape check."},
    )
    assert updated["ok"] is True
    card = updated["card"]
    assert set(card.keys()) == {"id", "title", "stage", "goal", "acceptance_criteria", "assignee"}
    assert card["title"] == "Updatable card"
    assert card["stage"] == "spec"
    assert card["goal"] == "Updated goal for shape check."
    assert card["acceptance_criteria"] == ["It works."]
    assert card["assignee"] is None
    assert card["id"].startswith("card_")


def test_move_card_tool_result_card():
    client = make_client()
    store = _store(client)
    ada = store.get_actor("human:ada")
    created = execute_tool(
        store,
        ada,
        "create_spec",
        {
            "title": "Movable card",
            "goal": "Verify the move_card tool result card shape.",
            "acceptance_criteria": ["It works."],
        },
    )
    assert created["ok"] is True

    # approve spec first (human-only)
    from app.services.cards import transition_card
    from app.schemas.cards import Stage, TransitionRequest

    card_id = created["card_id"]
    transition_card(store, ada, card_id, TransitionRequest(to_stage=Stage.READY))

    moved = execute_tool(
        store,
        ada,
        "move_card",
        {"card": "Movable card", "to_stage": "building"},
    )
    assert moved["ok"] is True
    card = moved["card"]
    assert set(card.keys()) == {"id", "title", "stage", "goal", "acceptance_criteria", "assignee"}
    assert card["title"] == "Movable card"
    assert card["stage"] == "building"
    assert card["goal"] == "Verify the move_card tool result card shape."
    assert card["acceptance_criteria"] == ["It works."]
    assert card["assignee"] == "human:ada"
    assert card["id"].startswith("card_")


def test_assign_card_tool_result():
    client = make_client()
    store = _store(client)
    ada = store.get_actor("human:ada")
    created = execute_tool(
        store,
        ada,
        "create_spec",
        {
            "title": "Assignable card",
            "goal": "Verify the assign_card tool result shape.",
            "acceptance_criteria": ["It works."],
        },
    )
    assert created["ok"] is True

    # approve spec and assign
    from app.services.cards import transition_card
    from app.schemas.cards import Stage, TransitionRequest

    card_id = created["card_id"]
    transition_card(store, ada, card_id, TransitionRequest(to_stage=Stage.READY))

    assigned = execute_tool(
        store,
        ada,
        "assign_card",
        {"card": "Assignable card", "assignee_id": "human:grace"},
    )
    assert assigned["ok"] is True
    assert assigned["card_id"].startswith("card_")
    assert "card" not in assigned  # assign_card does not return a "card" field

    cleared = execute_tool(
        store,
        ada,
        "assign_card",
        {"card": "Assignable card", "assignee_id": ""},
    )
    assert cleared["ok"] is True
    assert cleared["card_id"].startswith("card_")
    assert "card" not in cleared