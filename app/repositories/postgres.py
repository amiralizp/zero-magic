"""PostgreSQL persistence for cards, comments, PRDs and the audit log.

Same method surface as ``InMemoryRepository``, so
services do not know which backend they talk to. Uses SQLAlchemy Core with
parameterised statements; no string formatting of values into SQL. The schema
is created by Alembic migrations (S10), not by this module.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..actors import SEED_ACTORS
from ..config import Settings
from ..records import CardRecord, CommentRecord, PRDRecord, UserRecord
from ..repositories.errors import RepositoryIntegrityError, RepositoryNotFoundError
from ..schemas.actors import Actor, ActorRole
from ..schemas.cards import Stage


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return value
    if isinstance(value, (list, dict)):
        return Jsonb(value)
    return value


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return list(parsed) if isinstance(parsed, list) else []
    return list(value)


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

# Whitelists for identifiers used in f-strings (values stay parameterised).
_ALLOWED_TABLES = frozenset(
    {"cards", "comments", "prds", "actors", "audit_log", "users"}
)
_ALLOWED_COLUMNS = frozenset(
    {
        "id", "title", "goal", "acceptance_criteria", "out_of_scope", "stage",
        "assignee_id", "created_by", "prd_id", "created_at", "updated_at",
        "version", "built_by", "depends_on", "card_id", "author_id", "body",
        "event", "subject_id", "actor_id", "details",
        "username", "password_hash", "role", "created_at",
    }
)


def _validate_schema(name: str) -> None:
    if not _SCHEMA_RE.fullmatch(name):
        raise ValueError("invalid schema name")


def _validate_table(name: str) -> None:
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"unknown table: {name!r}")


def _validate_column(name: str) -> None:
    if name not in _ALLOWED_COLUMNS:
        raise ValueError(f"unknown column: {name!r}")


class PostgresRepository:
    def __init__(self, settings: Settings, *, schema: str = "public") -> None:
        _validate_schema(schema)
        self._settings = settings
        self._schema = schema
        self._lock = threading.RLock()
        self._engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)
        self.kind = "postgres"
        self._seed_actors()

    # -- helpers ---------------------------------------------------------

    def _conn(self):
        conn = self._engine.connect()
        # schema is validated in __init__; safe to interpolate as identifier.
        conn.execute(text(f'SET search_path TO "{self._schema}"'))
        return conn

    def _seed_actors(self) -> None:
        with self._conn() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM actors")).scalar()
            if count and count > 0:
                conn.commit()
                return
            for actor in SEED_ACTORS:
                conn.execute(
                    text(
                        "INSERT INTO actors (id, display_name, role) VALUES (:id, :dn, :role) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {"id": actor.id, "dn": actor.display_name, "role": actor.role.value},
                )
            conn.commit()

    # -- actors ----------------------------------------------------------

    def get_actor(self, actor_id: str | None) -> Actor | None:
        if actor_id is None:
            return None
        with self._conn() as conn:
            row = conn.execute(
                text("SELECT id, display_name, role FROM actors WHERE id = :id"),
                {"id": actor_id},
            ).fetchone()
        if row is None:
            return None
        return Actor(id=row[0], display_name=row[1], role=ActorRole(row[2]))

    def list_actors(self) -> list[Actor]:
        with self._conn() as conn:
            rows = conn.execute(
                text("SELECT id, display_name, role FROM actors ORDER BY id")
            ).fetchall()
        return [Actor(id=r[0], display_name=r[1], role=ActorRole(r[2])) for r in rows]

    # -- users -----------------------------------------------------------

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        role: ActorRole,
        actor_id: str,
    ) -> UserRecord:
        user_id = f"usr_{secrets.token_hex(6)}"
        now = _utcnow()
        try:
            with self._conn() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (id, username, password_hash, role, actor_id, created_at) "
                        "VALUES (:id, :username, :password_hash, :role, :actor_id, :created_at)"
                    ),
                    {
                        "id": user_id,
                        "username": username,
                        "password_hash": password_hash,
                        "role": role.value,
                        "actor_id": actor_id,
                        "created_at": now,
                    },
                )
                conn.commit()
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                raise RepositoryIntegrityError(
                    "duplicate username or unknown actor"
                ) from exc
            raise
        user = self.get_user_by_username(username)
        if user is None:
            raise RuntimeError(f"user {username!r} vanished after insert")
        return user

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                text(
                    "SELECT id, username, password_hash, role, actor_id, created_at "
                    "FROM users WHERE username = :username"
                ),
                {"username": username},
            ).fetchone()
        return None if row is None else self._user(row)

    def get_user_by_actor_id(self, actor_id: str) -> UserRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                text(
                    "SELECT id, username, password_hash, role, actor_id, created_at "
                    "FROM users WHERE actor_id = :actor_id"
                ),
                {"actor_id": actor_id},
            ).fetchone()
        return None if row is None else self._user(row)

    def list_users(self) -> list[UserRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, username, password_hash, role, actor_id, created_at "
                    "FROM users ORDER BY username"
                )
            ).fetchall()
        return [self._user(row) for row in rows]

    # -- cards -----------------------------------------------------------

    def _new_id(self, prefix: str, table: str, col: str = "id") -> str:
        _validate_table(table)
        _validate_column(col)
        for _ in range(5):
            candidate = f"{prefix}_{__import__('secrets').token_hex(5)}"
            with self._conn() as conn:
                exists = conn.execute(
                    text(f"SELECT 1 FROM {table} WHERE {col} = :c"), {"c": candidate}
                ).fetchone()
            if not exists:
                return candidate
        raise RuntimeError(f"could not allocate a {prefix} id")

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
        card_id = self._new_id("card", "cards")
        now = _utcnow()
        try:
            with self._conn() as conn:
                conn.execute(
                    text(
                        "INSERT INTO cards (id, title, goal, acceptance_criteria, out_of_scope, "
                        "stage, assignee_id, created_by, prd_id, created_at, updated_at, "
                        "version, built_by, depends_on) "
                        "VALUES (:id, :title, :goal, :ac, :os, :stage, :assignee, :created_by, "
                        ":prd_id, :created_at, :updated_at, 1, NULL, :depends_on)"
                    ),
                    {
                        "id": card_id,
                        "title": title,
                        "goal": goal,
                        "ac": _json(acceptance_criteria),
                        "os": _json(out_of_scope),
                        "stage": Stage.SPEC.value,
                        "assignee": assignee_id,
                        "created_by": created_by,
                        "prd_id": prd_id,
                        "created_at": now,
                        "updated_at": now,
                        "depends_on": _json(depends_on or []),
                    },
                )
                conn.commit()
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                raise RepositoryIntegrityError(
                    "referenced id does not exist"
                ) from exc
            raise
        self.audit("card.created", card_id, created_by)
        record = self.get_card(card_id)
        if record is None:
            raise RuntimeError(f"card {card_id} vanished after insert")
        return record

    def get_card(self, card_id: str) -> CardRecord | None:
        with self._conn() as conn:
            _validate_table("cards")
            row = conn.execute(
                text(
                    "SELECT id, title, goal, acceptance_criteria, out_of_scope, stage, "
                    "assignee_id, created_by, prd_id, created_at, updated_at, version, "
                    "built_by, depends_on FROM cards WHERE id = :id"
                ),
                {"id": card_id},
            ).fetchone()
        if row is None:
            return None
        return self._card(row)

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
        sql = (
            "SELECT id, title, goal, acceptance_criteria, out_of_scope, stage, "
            "assignee_id, created_by, prd_id, created_at, updated_at, version, "
            "built_by, depends_on FROM cards"
        )
        params: dict[str, Any] = {}
        clauses: list[str] = []
        if stage is not None:
            clauses.append("stage = :stage")
            params["stage"] = stage.value
        if assignee_id is not None:
            clauses.append("assignee_id = :assignee_id")
            params["assignee_id"] = assignee_id
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, id"
        with self._conn() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        items = [self._card(row) for row in rows]
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
        return items

    def update_card(
        self, card_id: str, *, actor_id: str | None = None, **changes: object
    ) -> CardRecord:
        columns = {
            "title": "title",
            "goal": "goal",
            "acceptance_criteria": "acceptance_criteria",
            "out_of_scope": "out_of_scope",
            "stage": "stage",
            "assignee_id": "assignee_id",
            "built_by": "built_by",
            "depends_on": "depends_on",
        }
        assignments: list[str] = []
        params: dict[str, Any] = {"card_id": card_id}
        for key, value in changes.items():
            column = columns.get(key)
            if column is None:
                raise ValueError(f"unknown card field {key!r}")
            _validate_column(column)
            if key in {"acceptance_criteria", "out_of_scope", "depends_on"}:
                if not isinstance(value, list):
                    raise ValueError(f"{column} must be a list")
                params[key] = _json(value)
            elif key == "stage":
                params[key] = value.value if isinstance(value, Stage) else str(value)
            else:
                params[key] = value
            assignments.append(f"{column} = :{key}")
        if not assignments:
            raise ValueError("nothing to update")
        assignments.append("updated_at = :updated_at")
        assignments.append("version = version + 1")
        params["updated_at"] = _utcnow()
        if self.get_card(card_id) is None:
            raise RepositoryNotFoundError(f"card {card_id!r} does not exist")
        _validate_table("cards")
        sql = f"UPDATE cards SET {', '.join(assignments)} WHERE id = :card_id"
        try:
            with self._conn() as conn:
                conn.execute(text(sql), params)
                conn.commit()
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                raise RepositoryIntegrityError(
                    "referenced id does not exist"
                ) from exc
            raise
        self.audit("card.updated", card_id, actor_id)
        record = self.get_card(card_id)
        if record is None:
            raise RepositoryNotFoundError(f"card {card_id!r} does not exist")
        return record

    def delete_card(self, card_id: str) -> CardRecord | None:
        record = self.get_card(card_id)
        if record is None:
            return None
        with self._conn() as conn:
            # comments cascade via FK ON DELETE CASCADE
            _validate_table("cards")
            conn.execute(text("DELETE FROM cards WHERE id = :id"), {"id": card_id})
            conn.commit()
        return record

    # -- comments -------------------------------------------------------

    def create_comment(self, card_id: str, author_id: str, body: str) -> CommentRecord:
        comment_id = f"cmt_{secrets.token_hex(5)}"
        now = _utcnow()
        try:
            with self._conn() as conn:
                conn.execute(
                    text(
                        "INSERT INTO comments (id, card_id, author_id, body, created_at) "
                        "VALUES (:id, :card_id, :author_id, :body, :created_at)"
                    ),
                    {
                        "id": comment_id,
                        "card_id": card_id,
                        "author_id": author_id,
                        "body": body,
                        "created_at": now,
                    },
                )
                conn.commit()
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                raise RepositoryIntegrityError(
                    "referenced id does not exist"
                ) from exc
            raise
        self.audit("comment.created", card_id, author_id, {"comment_id": comment_id})
        return CommentRecord(
            id=comment_id,
            card_id=card_id,
            author_id=author_id,
            body=body,
            created_at=now,
        )

    def list_comments(self, card_id: str) -> list[CommentRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, card_id, author_id, body, created_at FROM comments "
                    "WHERE card_id = :card_id ORDER BY created_at, id"
                ),
                {"card_id": card_id},
            ).fetchall()
        return [
            CommentRecord(
                id=r[0],
                card_id=r[1],
                author_id=r[2],
                body=r[3],
                created_at=_aware(r[4]),
            )
            for r in rows
        ]

    # -- PRDs -----------------------------------------------------------

    def create_prd(self, *, title: str, body: str, created_by: str) -> PRDRecord:
        prd_id = f"prd_{secrets.token_hex(5)}"
        now = _utcnow()
        with self._conn() as conn:
            conn.execute(
                text(
                    "INSERT INTO prds (id, title, body, created_by, created_at) "
                    "VALUES (:id, :title, :body, :created_by, :created_at)"
                ),
                {
                    "id": prd_id,
                    "title": title,
                    "body": body,
                    "created_by": created_by,
                    "created_at": now,
                },
            )
            conn.commit()
        self.audit("prd.created", prd_id, created_by)
        record = self.get_prd(prd_id)
        if record is None:
            raise RuntimeError(f"PRD {prd_id} vanished after insert")
        return record

    def get_prd(self, prd_id: str) -> PRDRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                text("SELECT id, title, body, created_by, created_at FROM prds WHERE id = :id"),
                {"id": prd_id},
            ).fetchone()
        if row is None:
            return None
        return PRDRecord(
            id=row[0],
            title=row[1],
            body=row[2],
            created_by=row[3],
            created_at=_aware(row[4]),
        )

    def list_prds(self) -> list[PRDRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, title, body, created_by, created_at FROM prds "
                    "ORDER BY created_at DESC, id DESC"
                )
            ).fetchall()
        return [
            PRDRecord(
                id=r[0],
                title=r[1],
                body=r[2],
                created_by=r[3],
                created_at=_aware(r[4]),
            )
            for r in rows
        ]

    @property
    def audit_log(self) -> list[dict[str, object]]:
        with self._conn() as conn:
            rows = conn.execute(
                text("SELECT event, subject_id, actor_id, created_at, details FROM audit_log ORDER BY id")
            ).fetchall()
        result: list[dict[str, object]] = []
        for r in rows:
            details = r[4]
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except (ValueError, TypeError):
                    pass
            result.append(
                {
                    "event": r[0],
                    "subject_id": r[1],
                    "actor_id": r[2],
                    "at": _aware(r[3]).isoformat() if isinstance(r[3], datetime) else str(r[3]),
                    "extra": details if details is not None else {},
                }
            )
        return result

    # -- audit ----------------------------------------------------------

    def audit(
        self,
        event: str,
        subject_id: str,
        actor_id: str | None,
        extra: dict[str, object] | None = None,
    ) -> None:
        details = json.dumps(extra, sort_keys=True, default=str, ensure_ascii=False) if extra else None
        with self._conn() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_log (event, subject_id, actor_id, created_at, details) "
                    "VALUES (:event, :subject_id, :actor_id, :created_at, :details)"
                ),
                {
                    "event": event,
                    "subject_id": subject_id,
                    "actor_id": actor_id,
                    "created_at": _utcnow(),
                    "details": details,
                },
            )
            conn.commit()

    # -- mapping --------------------------------------------------------

    @staticmethod
    def _user(row: Any) -> UserRecord:
        return UserRecord(
            id=row[0],
            username=row[1],
            password_hash=row[2],
            role=ActorRole(row[3]),
            actor_id=row[4],
            created_at=_aware(row[5]),
        )

    @staticmethod
    def _card(row: Any) -> CardRecord:
        return CardRecord(
            id=row[0],
            title=row[1],
            goal=row[2],
            acceptance_criteria=_list(row[3]),
            out_of_scope=_list(row[4]),
            stage=Stage(row[5]),
            assignee_id=row[6],
            created_by=row[7],
            prd_id=row[8],
            created_at=_aware(row[9]),
            updated_at=_aware(row[10]),
            version=row[11],
            built_by=row[12],
            depends_on=_list(row[13]),
        )
