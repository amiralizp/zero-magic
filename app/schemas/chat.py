"""Request models for the chat completion endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionRequest(BaseModel):
    """Strict body for ``POST /api/v1/chat/completions``."""

    model_config = ConfigDict(extra="forbid")

    messages: list[Any] | None = None
    model: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)
    actor: str | None = None
