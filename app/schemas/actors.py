"""Actors are humans or agents. The distinction drives the guardrails."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ActorRole(str, Enum):
    HUMAN = "human"
    AGENT = "agent"


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    role: ActorRole


class ActorList(BaseModel):
    items: list[Actor]
    total: int
