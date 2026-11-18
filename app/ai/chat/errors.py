"""Framework-free error type for chat upstream failures.

Carries the same information the router previously read from httpx response
objects, so ``app/api/chat.py`` can stay free of httpx (ADR 0007).
"""

from __future__ import annotations


class ChatUpstreamError(Exception):
    """An upstream (provider) failure, translated from an httpx error."""

    def __init__(self, *, status: int | None, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.kind = kind
        self.detail = detail
