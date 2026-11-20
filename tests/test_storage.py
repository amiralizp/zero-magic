"""Storage selection: PostgreSQL when configured, memory otherwise.

The PostgreSQL path is exercised against a real database by the contract tests
when GANTRY_TEST_DATABASE_URL is set; these tests need no running database.
"""

from __future__ import annotations

from app.config import Settings
from app.repositories.factory import build_repository
from app.repositories.memory import InMemoryRepository

import tests.helpers as helpers


def test_no_login_keeps_the_in_memory_store():
    store = build_repository(Settings())
    assert isinstance(store, InMemoryRepository)


def test_health_reports_which_store_is_active(client):
    payload = client.get("/api/v1/health").json()
    assert payload["storage"] == "memory"


def test_database_url_selects_postgres_without_connecting(monkeypatch):
    from app.repositories import factory

    captured: list[Settings] = []

    class FakePostgresRepository:
        kind = "postgres"

        def __init__(self, settings: Settings) -> None:
            captured.append(settings)

    monkeypatch.setattr(factory, "PostgresRepository", FakePostgresRepository)
    settings = Settings(database_url="postgresql+psycopg://u:p@127.0.0.1:5432/db")
    store = build_repository(settings)
    assert isinstance(store, FakePostgresRepository)
    assert captured == [settings]
