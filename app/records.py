"""Neutral data records shared by both store implementations.

These are plain dataclasses with no behaviour, no validation and no framework
imports (ADR 0007). Both ``InMemoryStore`` and ``SqlServerStore`` build and
read them, so they live in a module neither store needs to import the other
from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .schemas.cards import Stage


@dataclass
class CardRecord:
    id: str
    title: str
    goal: str
    acceptance_criteria: list[str]
    out_of_scope: list[str]
    stage: Stage
    assignee_id: str | None
    created_by: str
    prd_id: str | None
    created_at: datetime
    updated_at: datetime
    version: int = 1
    built_by: str | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class CommentRecord:
    id: str
    card_id: str
    author_id: str
    body: str
    created_at: datetime


@dataclass
class PRDRecord:
    id: str
    title: str
    body: str
    created_by: str
    created_at: datetime
