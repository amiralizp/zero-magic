"""Card contracts.

The funnel stages are deliberately a closed enum. A card can only move along
the transitions in ``app.services.cards``; this module only describes shape.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .actors import Actor

MAX_CRITERIA = 5
MAX_SCOPE_ITEMS = 10
MAX_CRITERION_LENGTH = 300
MAX_SCOPE_ITEM_LENGTH = 200
_INVISIBLE_CHARS = frozenset("\u200b\u200c\u200d\u2060\ufeff\u3164\u115f\u1160\u180e")


class Stage(str, Enum):
    SPEC = "spec"
    READY = "ready"
    BUILDING = "building"
    CHECKS = "checks"
    VALIDATION = "validation"
    DONE = "done"


STAGE_ORDER: tuple[Stage, ...] = (
    Stage.SPEC,
    Stage.READY,
    Stage.BUILDING,
    Stage.CHECKS,
    Stage.VALIDATION,
    Stage.DONE,
)


def _clean_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("must not be blank")
    visible = "".join(ch for ch in cleaned if ch not in _INVISIBLE_CHARS)
    if not visible.strip():
        raise ValueError("must not be blank")
    return cleaned


def _clean_criteria(items: list[str]) -> list[str]:
    cleaned = [_clean_text(item) for item in items]
    if any(len(item) > MAX_CRITERION_LENGTH for item in cleaned):
        raise ValueError(
            f"acceptance criteria items must be at most {MAX_CRITERION_LENGTH} characters"
        )
    if len({item.casefold() for item in cleaned}) != len(cleaned):
        raise ValueError("acceptance criteria must be unique")
    return cleaned


def _clean_scope(items: list[str]) -> list[str]:
    cleaned = [_clean_text(item) for item in items]
    if any(len(item) > MAX_SCOPE_ITEM_LENGTH for item in cleaned):
        raise ValueError(
            f"out of scope items must be at most {MAX_SCOPE_ITEM_LENGTH} characters"
        )
    if len(cleaned) > MAX_SCOPE_ITEMS:
        raise ValueError(f"out_of_scope accepts at most {MAX_SCOPE_ITEMS} items")
    return cleaned


class CardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=10, max_length=400)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=MAX_CRITERIA)
    out_of_scope: list[str] = Field(default_factory=list, max_length=MAX_SCOPE_ITEMS)
    assignee_id: str | None = Field(default=None, max_length=80)

    @field_validator("title", "goal")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def _criteria(cls, value: list[str]) -> list[str]:
        return _clean_criteria(value)

    @field_validator("out_of_scope")
    @classmethod
    def _scope(cls, value: list[str]) -> list[str]:
        return _clean_scope(value)


class CardUpdate(BaseModel):
    """Editing the written spec is allowed only while the card is in Spec."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=80)
    goal: str | None = Field(default=None, min_length=10, max_length=400)
    acceptance_criteria: list[str] | None = Field(
        default=None, min_length=1, max_length=MAX_CRITERIA
    )
    out_of_scope: list[str] | None = Field(
        default=None, max_length=MAX_SCOPE_ITEMS
    )

    @field_validator("title", "goal")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        return None if value is None else _clean_text(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def _criteria(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_criteria(value)

    @field_validator("out_of_scope")
    @classmethod
    def _scope(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_scope(value)

    @model_validator(mode="after")
    def _at_least_one(self) -> "CardUpdate":
        if not any(
            value is not None
            for value in (
                self.title,
                self.goal,
                self.acceptance_criteria,
                self.out_of_scope,
            )
        ):
            raise ValueError("provide at least one field to update")
        return self


class CardRead(BaseModel):
    """Public card shape. Internal fields (builder, history) never appear here."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    goal: str
    acceptance_criteria: list[str]
    out_of_scope: list[str]
    stage: Stage
    assignee: Actor | None
    created_by: Actor
    depends_on: list[str] = Field(default_factory=list)
    prd_id: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source(self) -> Literal["manual", "prd"]:
        return "prd" if self.prd_id else "manual"


class CardList(BaseModel):
    items: list[CardRead]
    total: int
    limit: int
    offset: int


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_stage: Stage
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AssigneeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required key, nullable value: null removes the assignee.
    assignee_id: str | None = Field(max_length=80)


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _clean_text(value)


class CommentRead(BaseModel):
    id: str
    card_id: str
    author: Actor
    body: str
    created_at: datetime


class CommentList(BaseModel):
    items: list[CommentRead]
    total: int
