"""Chat policy: preconditions and error mapping, framework-free.

This module owns the chat-specific rules (missing key, actor fallback from the
request body, upstream status -> hint mapping) so the router only handles HTTP
and SSE framing. It imports nothing from FastAPI, Starlette or httpx (ADR 0007).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..repositories.factory import Repository
from ..domain_errors import AppError
from ..schemas.actors import Actor


def require_chat_key(settings: Settings) -> None:
    """Raise if the chat provider key is not configured."""
    if not settings.chat_api_key:
        raise AppError(
            status_code=401,
            code="missing_chat_key",
            message=f"CHAT_API_KEY for {settings.chat_provider} is not configured.",
        )


def resolve_actor(store: Repository, actor: Actor | None, claimed: Any) -> Actor | None:
    """Resolve the acting actor, preferring the header over the body claim.

    Returns ``None`` when neither is present. Raises ``unknown_actor`` when the
    body claims an id that is not registered.
    """
    if actor is not None:
        return actor
    if not isinstance(claimed, str) or not claimed.strip():
        return None
    resolved = store.get_actor(claimed.strip())
    if resolved is None:
        raise AppError(
            status_code=401,
            code="unknown_actor",
            message=f"Actor {claimed!r} is not registered.",
        )
    return resolved


def upstream_hint(settings: Settings, status: int) -> str | None:
    """Return a user-facing hint for a known upstream status, else None."""
    if status == 401:
        return (
            f"{settings.chat_provider} rejected the API key. Check CHAT_API_KEY in .env "
            "and restart the server."
        )
    if status == 403:
        return (
            f"{settings.chat_provider} answered 403 Forbidden. That is often a network "
            "block rather than a bad key. Try a VPN, or set HTTPS_PROXY in .env, then "
            "restart the server."
        )
    if status == 402:
        return (
            f"{settings.chat_provider} refused the request because the account has no "
            "remaining balance. Top up the account, then try again."
        )
    if status == 429:
        return (
            f"{settings.chat_provider} rate-limited this model. "
            "Free-model quota is separate from a Go subscription; pick a Go model and try again."
        )
    return None
