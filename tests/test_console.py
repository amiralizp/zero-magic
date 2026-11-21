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
    assert "<strong>Gantry</strong>" in body
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
    assert "Authorization" in script.text
    assert "Bearer ${state.token}" in script.text
    assert "authHeaders" in script.text


def test_console_includes_the_ai_chat_panel(client):
    body = client.get("/console").text
    assert 'id="gantryChatPanel"' in body
    assert 'id="gantryChatFab"' in body
    assert "Powered by OpenCode" in body


def test_console_chat_can_change_the_board(client):
    assert "create a spec" in client.get("/console").text
    script = client.get("/console/assets/console.js").text
    assert "gantry_tool" in script
    assert "Authorization" in script


def test_console_chat_steps_aside_for_the_card_drawer(client):
    styles = client.get("/console/assets/console.css").text
    assert "body.overlay-open .gantry-chat-fab" in styles
    assert "body.overlay-open .gantry-chat-panel" in styles


def test_console_explains_why_done_can_be_refused(client):
    script = client.get("/console/assets/console.js").text
    assert "self_validation_blocked" in script
    assert "A different human must validate" in script


def test_console_is_linked_from_root_but_absent_from_openapi(client):
    root = client.get("/").json()
    assert root["console"] == "/console"

    paths = client.get("/openapi.json").json()["paths"]
    assert "/console" not in paths
    assert "/console/assets/console.css" not in paths


def test_console_has_a_login_form_and_no_actor_picker(client):
    body = client.get("/console").text
    assert 'id="login-form"' in body
    assert 'id="login-button"' in body
    assert 'id="logout-button"' in body
    assert "actor-select" not in body
    assert "X-Actor-Id" not in body


def test_standalone_chat_shares_the_same_token(client):
    page = client.get("/chat").text
    assert 'id="chatLoginForm"' in page
    assert 'id="chatLogoutBtn"' in page
    script = client.get("/chat/assets/app.js").text
    assert "Bearer ${authToken}" in script
    assert "actor:" not in script


def test_console_and_chat_keep_access_token_in_memory_only(client):
    console_js = client.get("/console/assets/console.js").text
    chat_js = client.get("/chat/assets/app.js").text
    for script in (console_js, chat_js):
        assert "localStorage.setItem('zm.token'" not in script
        assert "sessionStorage" not in script
        assert "document.cookie" not in script
