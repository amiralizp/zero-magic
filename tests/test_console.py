"""The interactive console is a static page served by the app.

It is deliberately not part of the OpenAPI contract: the API is the product,
the console is a convenience for using it by hand.
"""

from __future__ import annotations


def test_console_is_served_as_html(client):
    response = client.get("/console")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert 'class="app"' in body
    assert "/console/assets/console.js" in body
    assert "/console/assets/console.css" in body


def test_console_assets_are_served(client):
    styles = client.get("/console/assets/console.css")
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    assert "--accent" in styles.text

    script = client.get("/console/assets/console.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "X-Actor-Id" in script.text


def test_console_is_linked_from_root_but_absent_from_openapi(client):
    root = client.get("/").json()
    assert root["console"] == "/console"

    paths = client.get("/openapi.json").json()["paths"]
    assert "/console" not in paths
    assert "/console/assets/console.css" not in paths
