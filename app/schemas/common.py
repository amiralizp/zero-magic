"""Shared schema helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    """Documented in OpenAPI so clients can rely on one failure shape."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
