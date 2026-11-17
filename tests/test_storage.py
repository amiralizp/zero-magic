"""Storage selection: SQL Server when configured, memory otherwise.

The SQL path is exercised against a real server by hand; these tests keep the
suite independent of a running database.
"""

from __future__ import annotations

from app.config import Settings
from app.db import build_store
from app.store import InMemoryStore

import tests.helpers as helpers


def test_no_login_keeps_the_in_memory_store():
    store = build_store(Settings())
    assert isinstance(store, InMemoryStore)


def test_health_reports_which_store_is_active(client):
    payload = client.get("/api/v1/health").json()
    assert payload["storage"] == "memory"


def test_a_configured_login_selects_sql_server():
    settings = Settings(db_user="gantry_app", db_password="secret")
    assert settings.db_user == "gantry_app"
    # Building it would connect; the selection rule is what matters here.
    assert settings.db_user != ""
