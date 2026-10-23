"""PRD and breakdown contracts.

``CardDraft`` and ``Breakdown`` are the structured-output contract for the
model. Validators are part of the contract: invalid model output is rejected
and retried rather than stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .actors import Actor
from .cards import CardRead

MAX_DRAFT_CARDS = 10
MAX_DRAFT_CRITERIA = 5


def _clean(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("must not be blank")
    return cleaned


class PRDCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=20, max_length=20_000)

    @field_validator("title", "body")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _clean(value)


class PRDRead(BaseModel):
    id: str
    title: str
    body: str
    created_by: Actor
    created_at: datetime


class PRDList(BaseModel):
    items: list[PRDRead]
    total: int


class CardDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=10, max_length=400)
    acceptance_criteria: list[str] = Field(
        min_length=1, max_length=MAX_DRAFT_CRITERIA
    )
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_DRAFT_CARDS)

    @field_validator("title", "goal")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def _criteria(cls, value: list[str]) -> list[str]:
        cleaned = [_clean(item) for item in value]
        if len({item.casefold() for item in cleaned}) != len(cleaned):
            raise ValueError("acceptance criteria must be unique")
        return cleaned

    @field_validator("depends_on")
    @classmethod
    def _deps(cls, value: list[str]) -> list[str]:
        cleaned = [_clean(dep) for dep in value]
        if len({dep.casefold() for dep in cleaned}) != len(cleaned):
            raise ValueError("depends_on must be unique")
        return cleaned


class Breakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[CardDraft] = Field(
        min_length=1, max_length=MAX_DRAFT_CARDS
    )

    @model_validator(mode="after")
    def _graph_is_sound(self) -> "Breakdown":
        titles = [card.title for card in self.cards]
        folded = [title.casefold() for title in titles]
        if len(set(folded)) != len(folded):
            raise ValueError("card titles must be unique")

        known = set(folded)
        for card in self.cards:
            for dep in card.depends_on:
                if dep.casefold() == card.title.casefold():
                    raise ValueError(f"card {card.title!r} cannot depend on itself")
                if dep.casefold() not in known:
                    raise ValueError(
                        f"card {card.title!r} depends on unknown card {dep!r}"
                    )

        graph = {
            card.title.casefold(): [dep.casefold() for dep in card.depends_on]
            for card in self.cards
        }
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(node: str) -> None:
            if node in done:
                return
            if node in visiting:
                raise ValueError("depends_on contains a cycle")
            visiting.add(node)
            for dep in graph[node]:
                visit(dep)
            visiting.remove(node)
            done.add(node)

        for node in graph:
            visit(node)
        return self


class BreakdownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None means "use DEFAULT_PROMPT_VERSION from the environment".
    prompt_version: Literal["v1", "v2"] | None = None
    model: str | None = Field(default=None, max_length=120)


class Usage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)


class BreakdownRead(BaseModel):
    prd_id: str
    cards: list[CardRead]
    model_used: str
    fallback_used: bool
    prompt_version: str
    attempts: int
    usage: Usage
    duration_ms: int
    warnings: list[str] = Field(default_factory=list)
