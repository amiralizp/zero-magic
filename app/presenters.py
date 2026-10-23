"""HTTP-independent helpers that turn records into response contracts."""

from __future__ import annotations

from .schemas.actors import Actor
from .schemas.cards import CardRead, CommentRead
from .schemas.prds import PRDRead
from .store import CardRecord, CommentRecord, InMemoryStore, PRDRecord


def _actor(store: InMemoryStore, actor_id: str) -> Actor:
    actor = store.get_actor(actor_id)
    if actor is None:
        raise RuntimeError(f"record references unknown actor {actor_id!r}")
    return actor


def card_to_read(store: InMemoryStore, record: CardRecord) -> CardRead:
    return CardRead(
        id=record.id,
        title=record.title,
        goal=record.goal,
        acceptance_criteria=record.acceptance_criteria,
        out_of_scope=record.out_of_scope,
        stage=record.stage,
        assignee=store.get_actor(record.assignee_id),
        created_by=_actor(store, record.created_by),
        depends_on=record.depends_on,
        prd_id=record.prd_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )


def comment_to_read(store: InMemoryStore, record: CommentRecord) -> CommentRead:
    return CommentRead(
        id=record.id,
        card_id=record.card_id,
        author=_actor(store, record.author_id),
        body=record.body,
        created_at=record.created_at,
    )


def prd_to_read(store: InMemoryStore, record: PRDRecord) -> PRDRead:
    return PRDRead(
        id=record.id,
        title=record.title,
        body=record.body,
        created_by=_actor(store, record.created_by),
        created_at=record.created_at,
    )
