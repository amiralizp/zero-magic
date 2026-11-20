"""Which store the app uses.

``DB_USER`` empty keeps the in-memory store: tests and a quick look at the API
need no SQL Server. A configured login switches every request to SQL Server,
where the same rows are visible from SSMS.
"""

from __future__ import annotations

from ..config import Settings
from .memory import InMemoryRepository
from .postgres import PostgresRepository
from .sql_server import SqlServerRepository

Repository = InMemoryRepository | SqlServerRepository | PostgresRepository


def build_repository(settings: Settings) -> Repository:
    # PostgreSQL wins when configured; then SQL Server; then in-memory.
    if settings.database_url:
        return PostgresRepository(settings)
    if settings.db_user:
        store = SqlServerRepository(settings)
        store.ensure_schema()
        return store
    return InMemoryRepository()
