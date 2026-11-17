"""Which store the app uses.

``DB_USER`` empty keeps the in-memory store: tests and a quick look at the API
need no SQL Server. A configured login switches every request to SQL Server,
where the same rows are visible from SSMS.
"""

from __future__ import annotations

from .config import Settings
from .store import InMemoryStore
from .store_sql import SqlServerStore

Store = InMemoryStore | SqlServerStore


def build_store(settings: Settings) -> Store:
    if not settings.db_user:
        return InMemoryStore()
    store = SqlServerStore(settings)
    store.ensure_schema()
    return store
