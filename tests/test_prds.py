"""PRD storage and read endpoints (week 3 input side)."""

from __future__ import annotations

from tests.helpers import (
    AGENT,
    HUMAN,
    SAMPLE_PRD,
    create_prd,
    headers,
    make_client,
)


def test_create_get_and_list_prds(client):
    first = create_prd(client, title="Card comments")
    second = create_prd(client, title="Card assignment", body=SAMPLE_PRD + "\n- One assignee.")

    assert first["id"].startswith("prd_")
    assert first["title"] == "Card comments"
    assert first["body"].startswith("# Card comments")
    assert first["created_by"]["id"] == HUMAN

    read = client.get(f"/api/v1/prds/{first['id']}")
    assert read.status_code == 200
    assert read.json() == first

    listed = client.get("/api/v1/prds").json()
    assert listed["total"] == 2
    assert [item["id"] for item in listed["items"]][0] == second["id"]
    stamps = [item["created_at"] for item in listed["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_prd_list_is_empty_initially(client):
    response = client.get("/api/v1/prds")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_only_humans_create_prds(client):
    response = client.post(
        "/api/v1/prds",
        headers=headers(AGENT),
        json={"title": "Agent-authored PRD", "body": SAMPLE_PRD},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "human_only"


def test_prd_create_requires_actor(client):
    response = client.post(
        "/api/v1/prds", json={"title": "No actor", "body": SAMPLE_PRD}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_actor"


def test_prd_validation(client):
    for payload in (
        {"title": "ab", "body": SAMPLE_PRD},
        {"title": "Valid title", "body": "too short"},
        {"title": "Valid title", "body": SAMPLE_PRD, "status": "approved"},
        {"body": SAMPLE_PRD},
    ):
        response = client.post("/api/v1/prds", headers=headers(HUMAN), json=payload)
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "invalid_payload"


def test_prd_body_limit_comes_from_settings():
    client = make_client(max_prd_chars=120)
    payload = {
        "title": "Too large",
        "body": "This line is long enough to pass the minimum. " * 5,
    }
    response = client.post("/api/v1/prds", headers=headers(HUMAN), json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "prd_too_large"
    assert error["details"] == {
        "length": len(payload["body"].strip()),
        "limit": 120,
    }

    # Nothing was stored.
    assert client.get("/api/v1/prds").json()["total"] == 0


def test_missing_prd_is_404(client):
    response = client.get("/api/v1/prds/prd_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "prd_not_found"
