"""SQL Server persistence for cards, comments, PRDs and the audit log.

Same method surface as ``InMemoryRepository``, so services do not know which one they
talk to. Writes are parameterised; lists are stored as JSON text.

python-tds is used instead of pyodbc because pyodbc has no wheel for this
interpreter and would need a C++ build.
"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytds

from ..actors import SEED_ACTORS
from ..config import Settings
from ..schemas.actors import Actor, ActorRole
from ..schemas.cards import Stage
from ..records import CardRecord, CommentRecord, PRDRecord
from .memory import utcnow

MAX_POOL = 4

CARD_COLUMNS = (
    "id, title, goal, acceptance_criteria, out_of_scope, stage, assignee_id, "
    "created_by, prd_id, created_at, updated_at, version, built_by, depends_on"
)

SCHEMA: tuple[str, ...] = (
    """
    IF OBJECT_ID('dbo.actors', 'U') IS NULL
    CREATE TABLE dbo.actors (
        id NVARCHAR(80) NOT NULL PRIMARY KEY,
        display_name NVARCHAR(120) NOT NULL,
        role NVARCHAR(20) NOT NULL
    )
    """,
    """
    IF OBJECT_ID('dbo.prds', 'U') IS NULL
    CREATE TABLE dbo.prds (
        id NVARCHAR(40) NOT NULL PRIMARY KEY,
        title NVARCHAR(120) NOT NULL,
        body NVARCHAR(MAX) NOT NULL,
        created_by NVARCHAR(80) NOT NULL,
        created_at DATETIME2(6) NOT NULL,
        CONSTRAINT FK_prds_created_by FOREIGN KEY (created_by) REFERENCES dbo.actors(id)
    )
    """,
    """
    IF OBJECT_ID('dbo.cards', 'U') IS NULL
    CREATE TABLE dbo.cards (
        id NVARCHAR(40) NOT NULL PRIMARY KEY,
        title NVARCHAR(80) NOT NULL,
        goal NVARCHAR(400) NOT NULL,
        acceptance_criteria NVARCHAR(MAX) NOT NULL,
        out_of_scope NVARCHAR(MAX) NOT NULL,
        stage NVARCHAR(20) NOT NULL,
        assignee_id NVARCHAR(80) NULL,
        created_by NVARCHAR(80) NOT NULL,
        prd_id NVARCHAR(40) NULL,
        created_at DATETIME2(6) NOT NULL,
        updated_at DATETIME2(6) NOT NULL,
        version INT NOT NULL DEFAULT 1,
        built_by NVARCHAR(80) NULL,
        depends_on NVARCHAR(MAX) NOT NULL DEFAULT '[]',
        CONSTRAINT FK_cards_assignee FOREIGN KEY (assignee_id) REFERENCES dbo.actors(id),
        CONSTRAINT FK_cards_created_by FOREIGN KEY (created_by) REFERENCES dbo.actors(id),
        CONSTRAINT FK_cards_built_by FOREIGN KEY (built_by) REFERENCES dbo.actors(id),
        CONSTRAINT FK_cards_prd FOREIGN KEY (prd_id) REFERENCES dbo.prds(id)
    )
    """,
    """
    IF OBJECT_ID('dbo.comments', 'U') IS NULL
    CREATE TABLE dbo.comments (
        id NVARCHAR(40) NOT NULL PRIMARY KEY,
        card_id NVARCHAR(40) NOT NULL,
        author_id NVARCHAR(80) NOT NULL,
        body NVARCHAR(2000) NOT NULL,
        created_at DATETIME2(6) NOT NULL,
        CONSTRAINT FK_comments_card FOREIGN KEY (card_id)
            REFERENCES dbo.cards(id) ON DELETE CASCADE,
        CONSTRAINT FK_comments_author FOREIGN KEY (author_id) REFERENCES dbo.actors(id)
    )
    """,
    """
    IF OBJECT_ID('dbo.audit_log', 'U') IS NULL
    CREATE TABLE dbo.audit_log (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        event NVARCHAR(80) NOT NULL,
        subject_id NVARCHAR(80) NOT NULL,
        actor_id NVARCHAR(80) NULL,
        created_at DATETIME2(6) NOT NULL,
        details NVARCHAR(MAX) NULL
    )
    """,
    "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_cards_stage') "
    "CREATE INDEX IX_cards_stage ON dbo.cards(stage)",
    "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_cards_assignee') "
    "CREATE INDEX IX_cards_assignee ON dbo.cards(assignee_id)",
    "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_comments_card') "
    "CREATE INDEX IX_comments_card ON dbo.comments(card_id, created_at)",
    "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_audit_created') "
    "CREATE INDEX IX_audit_created ON dbo.audit_log(created_at)",
)


def _naive(value: datetime) -> datetime:
    """SQL Server stores DATETIME2 without an offset; the app means UTC."""

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _json(items: list[str] | None) -> str:
    return json.dumps(items or [], ensure_ascii=False)


def _list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


class SqlServerRepository:
    """The durable store. One pooled connection per call, guarded by a lock."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._idle: list[pytds.Connection] = []
        self.kind = "sqlserver"

    # -- connections -----------------------------------------------------

    def _open(self) -> pytds.Connection:
        return pytds.connect(
            dsn=self._settings.db_server,
            database=self._settings.db_name,
            user=self._settings.db_user,
            password=self._settings.db_password,
            autocommit=True,
            login_timeout=10,
            timeout=30,
        )

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        connection = None
        with self._lock:
            if self._idle:
                connection = self._idle.pop()
        if connection is None:
            connection = self._open()
        cursor = connection.cursor()
        try:
            yield cursor
        except Exception:
            cursor.close()
            try:
                connection.close()
            except Exception:
                pass
            raise
        else:
            cursor.close()
            with self._lock:
                if len(self._idle) < MAX_POOL:
                    self._idle.append(connection)
                    connection = None
            if connection is not None:
                connection.close()

    # -- schema ----------------------------------------------------------

    def ensure_schema(self) -> None:
        with self._cursor() as cursor:
            for statement in SCHEMA:
                cursor.execute(statement)
            for actor in SEED_ACTORS:
                cursor.execute(
                    "IF NOT EXISTS (SELECT 1 FROM dbo.actors WHERE id = %s) "
                    "INSERT INTO dbo.actors (id, display_name, role) VALUES (%s, %s, %s)",
                    (actor.id, actor.id, actor.display_name, actor.role.value),
                )

    # -- actors ---------------------------------------------------------

    def get_actor(self, actor_id: str | None) -> Actor | None:
        if actor_id is None:
            return None
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT id, display_name, role FROM dbo.actors WHERE id = %s", (actor_id,)
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return Actor(id=row[0], display_name=row[1], role=ActorRole(row[2]))

    def list_actors(self) -> list[Actor]:
        with self._cursor() as cursor:
            cursor.execute("SELECT id, display_name, role FROM dbo.actors ORDER BY id")
            rows = cursor.fetchall()
        return [Actor(id=row[0], display_name=row[1], role=ActorRole(row[2])) for row in rows]

    # -- cards ----------------------------------------------------------

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
        now = _naive(utcnow())
        for _ in range(5):
            card_id = f"card_{secrets.token_hex(5)}"
            try:
                with self._cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO dbo.cards (id, title, goal, acceptance_criteria, "
                        "out_of_scope, stage, assignee_id, created_by, prd_id, created_at, "
                        "updated_at, version, built_by, depends_on) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NULL, %s)",
                        (
                            card_id,
                            title,
                            goal,
                            _json(acceptance_criteria),
                            _json(out_of_scope),
                            Stage.SPEC.value,
                            assignee_id,
                            created_by,
                            prd_id,
                            now,
                            now,
                            _json(depends_on),
                        ),
                    )
                break
            except pytds.IntegrityError:
                continue
        else:  # pragma: no cover - 40 bits of entropy, five attempts
            raise RuntimeError("could not allocate a card id")

        self.audit("card.created", card_id, created_by)
        record = self.get_card(card_id)
        if record is None:  # pragma: no cover - the insert just succeeded
            raise RuntimeError(f"card {card_id} vanished after insert")
        return record

    def get_card(self, card_id: str) -> CardRecord | None:
        with self._cursor() as cursor:
            cursor.execute(f"SELECT {CARD_COLUMNS} FROM dbo.cards WHERE id = %s", (card_id,))
            row = cursor.fetchone()
        return self._card(row) if row else None

    def list_cards(
        self,
        *,
        stage: Stage | None = None,
        assignee_id: str | None = None,
        query: str | None = None,
    ) -> list[CardRecord]:
        where: list[str] = []
        params: list[Any] = []
        if stage is not None:
            where.append("stage = %s")
            params.append(stage.value)
        if assignee_id is not None:
            where.append("assignee_id = %s")
            params.append(assignee_id)
        if query:
            needle = f"%{query.strip()}%"
            where.append("(title LIKE %s OR goal LIKE %s OR acceptance_criteria LIKE %s)")
            params.extend([needle, needle, needle])
        sql = f"SELECT {CARD_COLUMNS} FROM dbo.cards"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at, id"
        with self._cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
        return [self._card(row) for row in rows]

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
        params: list[Any] = []
        for key, value in changes.items():
            column = columns.get(key)
            if column is None:
                raise ValueError(f"unknown card field {key!r}")
            if key in {"acceptance_criteria", "out_of_scope", "depends_on"}:
                params.append(_json(value if isinstance(value, list) else None))
            elif key == "stage":
                params.append(value.value if isinstance(value, Stage) else str(value))
            else:
                params.append(value)
            assignments.append(f"{column} = %s")
        if not assignments:
            raise ValueError("nothing to update")
        assignments.extend(["updated_at = %s", "version = version + 1"])
        params.extend([_naive(utcnow()), card_id])
        with self._cursor() as cursor:
            cursor.execute(
                f"UPDATE dbo.cards SET {', '.join(assignments)} WHERE id = %s", tuple(params)
            )
        self.audit("card.updated", card_id, actor_id)
        record = self.get_card(card_id)
        if record is None:
            raise RuntimeError(f"card {card_id} does not exist")
        return record

    def delete_card(self, card_id: str) -> CardRecord | None:
        record = self.get_card(card_id)
        if record is None:
            return None
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM dbo.cards WHERE id = %s", (card_id,))
        return record

    # -- comments -------------------------------------------------------

    def create_comment(self, card_id: str, author_id: str, body: str) -> CommentRecord:
        comment_id = f"cmt_{secrets.token_hex(5)}"
        now = _naive(utcnow())
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO dbo.comments (id, card_id, author_id, body, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (comment_id, card_id, author_id, body, now),
            )
        self.audit("comment.created", card_id, author_id, {"comment_id": comment_id})
        return CommentRecord(
            id=comment_id,
            card_id=card_id,
            author_id=author_id,
            body=body,
            created_at=_aware(now),
        )

    def list_comments(self, card_id: str) -> list[CommentRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT id, card_id, author_id, body, created_at FROM dbo.comments "
                "WHERE card_id = %s ORDER BY created_at, id",
                (card_id,),
            )
            rows = cursor.fetchall()
        return [
            CommentRecord(
                id=row[0],
                card_id=row[1],
                author_id=row[2],
                body=row[3],
                created_at=_aware(row[4]),
            )
            for row in rows
        ]

    # -- PRDs -----------------------------------------------------------

    def create_prd(self, *, title: str, body: str, created_by: str) -> PRDRecord:
        prd_id = f"prd_{secrets.token_hex(5)}"
        now = _naive(utcnow())
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO dbo.prds (id, title, body, created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (prd_id, title, body, created_by, now),
            )
        self.audit("prd.created", prd_id, created_by)
        record = self.get_prd(prd_id)
        if record is None:  # pragma: no cover - the insert just succeeded
            raise RuntimeError(f"PRD {prd_id} vanished after insert")
        return record

    def get_prd(self, prd_id: str) -> PRDRecord | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT id, title, body, created_by, created_at FROM dbo.prds WHERE id = %s",
                (prd_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return PRDRecord(
            id=row[0], title=row[1], body=row[2], created_by=row[3], created_at=_aware(row[4])
        )

    def list_prds(self) -> list[PRDRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT id, title, body, created_by, created_at FROM dbo.prds "
                "ORDER BY created_at DESC, id DESC"
            )
            rows = cursor.fetchall()
        return [
            PRDRecord(
                id=row[0],
                title=row[1],
                body=row[2],
                created_by=row[3],
                created_at=_aware(row[4]),
            )
            for row in rows
        ]

    # -- audit ----------------------------------------------------------

    def audit(
        self,
        event: str,
        subject_id: str,
        actor_id: str | None,
        extra: dict[str, object] | None = None,
    ) -> None:
        details = json.dumps(extra, ensure_ascii=False) if extra else None
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO dbo.audit_log (event, subject_id, actor_id, created_at, details) "
                "VALUES (%s, %s, %s, %s, %s)",
                (event, subject_id, actor_id, _naive(utcnow()), details),
            )

    # -- mapping --------------------------------------------------------

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
