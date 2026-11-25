"""In-memory persistence.

Week 5 replaces this with PostgreSQL and migrations. Until then a lock around
plain dictionaries is enough for one process, and the rest of the app talks to
this small interface rather than to the dictionaries.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import replace
from datetime import datetime, timezone

from ..actors import SEED_ACTORS
from ..records import CardRecord, CommentRecord, PRDRecord, UserRecord
from ..repositories.errors import RepositoryIntegrityError, RepositoryNotFoundError
from ..schemas.actors import Actor, ActorRole
from ..schemas.cards import Stage

# Re-export so existing ``from app.store import CardRecord`` keeps working.
__all__ = [
    "CardRecord",
    "CommentRecord",
    "PRDRecord",
    "UserRecord",
    "InMemoryRepository",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryRepository:
    def __init__(self, actors: tuple[Actor, ...] = SEED_ACTORS) -> None:
        self.kind = "memory"
        self._lock = threading.RLock()
        self.actors: dict[str, Actor] = {actor.id: actor for actor in actors}
        self.cards: dict[str, CardRecord] = {}
        self.comments: dict[str, CommentRecord] = {}
        self.prds: dict[str, PRDRecord] = {}
        self.users: dict[str, UserRecord] = {}
        self.audit_log: list[dict[str, object]] = []

    # -- actors ---------------------------------------------------------

    def get_actor(self, actor_id: str | None) -> Actor | None:
        if actor_id is None:
            return None
        return self.actors.get(actor_id)

    def list_actors(self) -> list[Actor]:
        return sorted(self.actors.values(), key=lambda actor: actor.id)

    # -- users ----------------------------------------------------------

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        role: ActorRole,
        actor_id: str,
    ) -> UserRecord:
        with self._lock:
            if any(user.username == username for user in self.users.values()):
                raise RepositoryIntegrityError(f"duplicate username: {username!r}")
            if actor_id not in self.actors:
                raise RepositoryIntegrityError(
                    f"unknown actor for user: {actor_id!r}"
                )
            record = UserRecord(
                id=self._new_id("usr", self.users),
                username=username,
                password_hash=password_hash,
                role=role,
                actor_id=actor_id,
                created_at=utcnow(),
            )
            self.users[record.id] = record
            return record

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self._lock:
            return next(
                (user for user in self.users.values() if user.username == username),
                None,
            )

    def get_user_by_actor_id(self, actor_id: str) -> UserRecord | None:
        with self._lock:
            return next(
                (user for user in self.users.values() if user.actor_id == actor_id),
                None,
            )

    def list_users(self) -> list[UserRecord]:
        with self._lock:
            return sorted(self.users.values(), key=lambda user: user.username)

    # -- cards ----------------------------------------------------------

    def _new_id(self, prefix: str, existing: dict[str, object]) -> str:
        while True:
            candidate = f"{prefix}_{secrets.token_hex(5)}"
            if candidate not in existing:
                return candidate

    def create_card(
        self,
        *,
        title: str,
        goal: str,
        acceptance_criteria: list[str],
        out_of_scope: list[str],
        created_by: str,
        assignee_id: str | None = None,
        prd_id: str | None = None,
        depends_on: list[str] | None = None,
    ) -> CardRecord:
        with self._lock:
            if created_by not in self.actors:
                raise RepositoryIntegrityError(
                    f"unknown actor for created_by: {created_by!r}"
                )
            if assignee_id is not None and assignee_id not in self.actors:
                raise RepositoryIntegrityError(
                    f"unknown actor for assignee_id: {assignee_id!r}"
                )
            if prd_id is not None and prd_id not in self.prds:
                raise RepositoryIntegrityError(
                    f"unknown prd for prd_id: {prd_id!r}"
                )
            now = utcnow()
            record = CardRecord(
                id=self._new_id("card", self.cards),
                title=title,
                goal=goal,
                acceptance_criteria=list(acceptance_criteria),
                out_of_scope=list(out_of_scope),
                stage=Stage.SPEC,
                assignee_id=assignee_id,
                created_by=created_by,
                prd_id=prd_id,
                created_at=now,
                updated_at=now,
                depends_on=list(depends_on or []),
            )
            self.cards[record.id] = record
            self.audit("card.created", record.id, created_by)
            return record

    def get_card(self, card_id: str) -> CardRecord | None:
        with self._lock:
            return self.cards.get(card_id)

    @staticmethod
    def _norm_search(text: str) -> str:
        return text.translate(
            str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "\u200c": "", "\u0640": ""})
        ).casefold()

    def list_cards(
        self,
        *,
        stage: Stage | None = None,
        assignee_id: str | None = None,
        query: str | None = None,
    ) -> list[CardRecord]:
        with self._lock:
            items = list(self.cards.values())
        if stage is not None:
            items = [card for card in items if card.stage is stage]
        if assignee_id is not None:
            items = [card for card in items if card.assignee_id == assignee_id]
        if query:
            needle = self._norm_search(query.strip())
            if needle:
                items = [
                    card
                    for card in items
                    if needle in self._norm_search(card.title)
                    or needle in self._norm_search(card.goal)
                    or any(needle in self._norm_search(item) for item in card.acceptance_criteria)
                ]
        return sorted(items, key=lambda card: (card.created_at, card.id))

    def update_card(
        self, card_id: str, *, actor_id: str | None = None, **changes: object
    ) -> CardRecord:
        with self._lock:
            if card_id not in self.cards:
                raise RepositoryNotFoundError(f"card {card_id!r} does not exist")
            if "built_by" in changes and changes["built_by"] is not None and changes["built_by"] not in self.actors:
                raise RepositoryIntegrityError(
                    f"unknown actor for built_by: {changes['built_by']!r}"
                )
            if "created_by" in changes and changes["created_by"] is not None and changes["created_by"] not in self.actors:
                raise RepositoryIntegrityError(
                    f"unknown actor for created_by: {changes['created_by']!r}"
                )
            if "assignee_id" in changes and changes["assignee_id"] is not None and changes["assignee_id"] not in self.actors:
                raise RepositoryIntegrityError(
                    f"unknown actor for assignee_id: {changes['assignee_id']!r}"
                )
            if "prd_id" in changes and changes["prd_id"] is not None and changes["prd_id"] not in self.prds:
                raise RepositoryIntegrityError(
                    f"unknown prd for prd_id: {changes['prd_id']!r}"
                )
            for _json_field in ("acceptance_criteria", "out_of_scope", "depends_on"):
                if _json_field in changes and not isinstance(changes[_json_field], list):
                    raise ValueError(f"{_json_field} must be a list")
            current = self.cards[card_id]
            updated = replace(
                current,
                **changes,
                updated_at=utcnow(),
                version=current.version + 1,
            )
            self.cards[card_id] = updated
            self.audit("card.updated", card_id, actor_id)
            return updated

    def delete_card(self, card_id: str) -> CardRecord | None:
        with self._lock:
            record = self.cards.pop(card_id, None)
            if record is not None:
                for comment_id in [
                    key for key, value in self.comments.items() if value.card_id == card_id
                ]:
                    self.comments.pop(comment_id, None)
            return record

    # -- comments -------------------------------------------------------

    def create_comment(self, card_id: str, author_id: str, body: str) -> CommentRecord:
        with self._lock:
            if card_id not in self.cards:
                raise RepositoryIntegrityError(
                    f"unknown card for card_id: {card_id!r}"
                )
            if author_id not in self.actors:
                raise RepositoryIntegrityError(
                    f"unknown actor for author_id: {author_id!r}"
                )
            record = CommentRecord(
                id=self._new_id("cmt", self.comments),
                card_id=card_id,
                author_id=author_id,
                body=body,
                created_at=utcnow(),
            )
            self.comments[record.id] = record
            self.audit("comment.created", card_id, author_id, {"comment_id": record.id})
            return record

    def list_comments(self, card_id: str) -> list[CommentRecord]:
        with self._lock:
            items = [
                comment for comment in self.comments.values() if comment.card_id == card_id
            ]
        return sorted(items, key=lambda comment: (comment.created_at, comment.id))

    # -- PRDs -----------------------------------------------------------

    def create_prd(self, *, title: str, body: str, created_by: str) -> PRDRecord:
        with self._lock:
            record = PRDRecord(
                id=self._new_id("prd", self.prds),
                title=title,
                body=body,
                created_by=created_by,
                created_at=utcnow(),
            )
            self.prds[record.id] = record
            self.audit("prd.created", record.id, created_by)
            return record

    def get_prd(self, prd_id: str) -> PRDRecord | None:
        with self._lock:
            return self.prds.get(prd_id)

    def list_prds(self) -> list[PRDRecord]:
        with self._lock:
            items = list(self.prds.values())
        return sorted(items, key=lambda prd: (prd.created_at, prd.id), reverse=True)

    # -- audit ----------------------------------------------------------

    def audit(
        self,
        event: str,
        subject_id: str,
        actor_id: str | None,
        extra: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            self.audit_log.append(
                {
                    "event": event,
                    "subject_id": subject_id,
                    "actor_id": actor_id,
                    "at": utcnow().isoformat(),
                    "extra": extra or {},
                }
            )
