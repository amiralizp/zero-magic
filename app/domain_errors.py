"""Framework-free error type.

This module intentionally imports nothing from FastAPI or Starlette (ADR 0007).
AppError is defined here so that services, the AI layer and the store can raise
and catch it without pulling in a web framework. ``app/errors.py`` re-exports it
for backwards compatibility.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """A failure we understand, with an HTTP status and a stable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers
