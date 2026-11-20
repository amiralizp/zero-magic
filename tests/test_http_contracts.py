"""Cross-cutting HTTP contracts: one error shape, CORS, request ids, OpenAPI."""

from __future__ import annotations

import pytest

from tests.helpers import HUMAN, card_payload, create_card, headers, raw_client


def assert_error_envelope(response, *, code: str) -> None:
    payload = response.json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert set(error) <= {"code", "message", "details"}


def test_unknown_path_uses_the_error_envelope(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert_error_envelope(response, code="not_found")


def test_wrong_method_uses_the_error_envelope(client):
    response = client.post("/api/v1/health")
    assert response.status_code == 405
    assert_error_envelope(response, code="method_not_allowed")


def test_malformed_json_uses_the_error_envelope(client):
    response = client.post(
        "/api/v1/cards",
        headers={**headers(HUMAN), "Content-Type": "application/json"},
        content=b'{"title": "broken"',
    )
    assert response.status_code in {400, 422}
    assert "error" in response.json()


def test_validation_details_name_the_field(client):
    response = client.post(
        "/api/v1/cards",
        headers=headers(HUMAN),
        json={**card_payload(), "acceptance_criteria": []},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_payload"
    locations = [".".join(item["location"]) for item in error["details"]]
    assert any("acceptance_criteria" in location for location in locations)
    for item in error["details"]:
        assert set(item) == {"location", "message", "type"}


def test_request_id_is_echoed(client):
    card = create_card(client)
    response = client.get(
        f"/api/v1/cards/{card['id']}", headers={"X-Request-Id": "req-123"}
    )
    assert response.headers["x-request-id"] == "req-123"


def test_request_id_is_generated_when_absent(client):
    first = client.get("/api/v1/health")
    second = client.get("/api/v1/health")
    assert len(first.headers["x-request-id"]) == 12
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_request_id_is_present_on_errors(client):
    response = client.get("/api/v1/cards/card_missing")
    assert response.status_code == 404
    assert response.headers["x-request-id"]


def test_cors_preflight_allows_the_configured_origin(client):
    response = client.options(
        "/api/v1/cards",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed = response.headers["access-control-allow-headers"].casefold()
    assert "authorization" in allowed


def test_cors_does_not_allow_arbitrary_origins(client):
    response = client.get(
        "/api/v1/health", headers={"Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in response.headers


def test_openapi_lists_every_endpoint_and_the_error_envelope(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()

    paths = spec["paths"]
    expected = {
        ("/api/v1/health", "get"),
        ("/api/v1/actors", "get"),
        ("/api/v1/meta", "get"),
        ("/api/v1/cards", "get"),
        ("/api/v1/cards", "post"),
        ("/api/v1/cards/{card_id}", "get"),
        ("/api/v1/cards/{card_id}", "patch"),
        ("/api/v1/cards/{card_id}", "delete"),
        ("/api/v1/cards/{card_id}/transition", "post"),
        ("/api/v1/cards/{card_id}/comments", "get"),
        ("/api/v1/cards/{card_id}/comments", "post"),
        ("/api/v1/cards/{card_id}/assignee", "put"),
        ("/api/v1/prds", "get"),
        ("/api/v1/prds", "post"),
        ("/api/v1/prds/{prd_id}", "get"),
        ("/api/v1/prds/{prd_id}/breakdown", "post"),
        ("/api/v1/auth/login", "post"),
        ("/api/v1/auth/me", "get"),
    }
    for path, method in expected:
        assert path in paths, path
        assert method in paths[path], (path, method)

    assert "ErrorEnvelope" in spec["components"]["schemas"]
    schemas = spec["components"]["schemas"]
    card_read = schemas["CardRead"]
    assert "built_by" not in card_read["properties"]
    assert "source" in card_read["properties"]


def test_docs_and_redoc_are_served(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    root = client.get("/").json()
    assert root["health"] == "/api/v1/health"


def test_meta_describes_the_real_state_machine(client):
    payload = client.get("/api/v1/meta").json()
    assert payload["stages"] == [
        "spec",
        "ready",
        "building",
        "checks",
        "validation",
        "done",
    ]
    assert payload["transitions"]["spec"] == ["ready"]
    assert payload["transitions"]["done"] == []
    assert payload["default_models"] == ["mock-strong", "mock-fast"]
    assert payload["prompt_versions"] == ["v1", "v2"]
    assert ["spec", "ready"] in payload["human_only_transitions"]
    assert ["validation", "done"] in payload["human_only_transitions"]
    assert ["ready", "building"] not in payload["human_only_transitions"]
    assert payload["limits"]["max_cards_per_breakdown"] == 10


def test_actor_directory_seeds_humans_and_agents(client):
    response = client.get("/api/v1/actors")
    assert response.status_code == 200
    payload = response.json()
    roles = {actor["role"] for actor in payload["items"]}
    assert roles == {"human", "agent"}
    assert payload["total"] == len(payload["items"]) == 6
    for actor in payload["items"]:
        assert actor["id"].startswith(("human:", "agent:"))


@pytest.mark.parametrize("header", ["X-Actor-Id", "x-actor-id", "X-ACTOR-ID"])
def test_legacy_actor_header_is_ignored(client, header):
    response = raw_client(client.app).post(
        "/api/v1/cards",
        headers={header: HUMAN},
        json=card_payload(),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_health_is_public_and_reports_the_version(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.3.0"
