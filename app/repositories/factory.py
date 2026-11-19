"""Which store the app uses.

``DB_USER`` empty keeps the in-memory store: tests and a quick look at the API
need no SQL Server. A configured login switches every request to SQL Server,
where the same rows are visible from SSMS.
"""

from __future__ import annotations

from ..config import Settings
from .memory import InMemoryRepository
from .sql_server import SqlServerRepository

Repository = InMemoryRepository | SqlServerRepository


def build_repository(settings: Settings) -> Repository:
    if not settings.db_user:
        return InMemoryRepository()
    store = SqlServerRepository(settings)
    store.ensure_schema()
    return store
