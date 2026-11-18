"""Behavior-lock tests for health, actors and meta endpoints (S8.4).

These tests pin the current behavior so the S8.4 refactor (injecting the
store dependency into meta endpoints) cannot change responses.
"""

from __future__ import annotations

from tests.helpers import make_client


def test_health_status_and_keys(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.3.0"
    assert payload["storage"] == "memory"
    assert set(payload.keys()) == {"status", "version", "environment", "storage"}


def test_actors_list_shape(client):
    response = client.get("/api/v1/actors")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 6
    assert len(payload["items"]) == 6
    assert set(payload.keys()) == {"items", "total"}
    for actor in payload["items"]:
        assert set(actor.keys()) == {"id", "display_name", "role"}


def test_meta_top_level_keys(client):
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {
        "stages",
        "transitions",
        "human_only_transitions",
        "models",
        "default_models",
        "prompt_versions",
        "limits",
    }