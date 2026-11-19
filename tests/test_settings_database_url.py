"""Settings: DATABASE_URL is read and kept out of repr (S9)."""

from __future__ import annotations

import os

import app.config as config_module
from app.config import Settings


def test_database_url_defaults_to_empty():
    settings = Settings()
    assert settings.database_url == ""


def test_from_env_reads_database_url(monkeypatch):
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:5432/db")
    settings = Settings.from_env()
    assert settings.database_url == "postgresql+psycopg://u:p@127.0.0.1:5432/db"


def test_database_url_is_not_in_repr():
    settings = Settings(database_url="s3cret-value")
    assert "s3cret-value" not in repr(settings)