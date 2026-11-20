"""Which store the app uses.

A configured ``DATABASE_URL`` selects PostgreSQL, the durable store. Without it
the in-memory repository is used: tests and a quick look at the API need no
database server.
"""

from __future__ import annotations

from ..config import Settings
from .memory import InMemoryRepository
from .postgres import PostgresRepository

Repository = InMemoryRepository | PostgresRepository


def build_repository(settings: Settings) -> Repository:
    if settings.database_url:
        return PostgresRepository(settings)
    return InMemoryRepository()
