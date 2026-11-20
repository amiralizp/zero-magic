"""Chat policy: preconditions and error mapping, framework-free.

This module owns the chat-specific rules (missing key and upstream status ->
hint mapping) so the router only handles HTTP and SSE framing. Identity comes
from a signed token, never from the request body. It imports nothing from
FastAPI, Starlette or httpx (ADR 0007).
"""

from __future__ import annotations

from ..config import Settings
from ..domain_errors import AppError


def require_chat_key(settings: Settings) -> None:
    """Raise if the chat provider key is not configured."""
    if not settings.chat_api_key:
        raise AppError(
            status_code=401,
            code="missing_chat_key",
            message=f"CHAT_API_KEY for {settings.chat_provider} is not configured.",
        )


def key_hint(settings: Settings) -> str:
    return (
        f"{settings.chat_provider} rejected the API key. Check CHAT_API_KEY in .env "
        "and restart the server."
    )


def blocked_hint(settings: Settings) -> str:
    return (
        f"{settings.chat_provider} answered 403 Forbidden. That is often a network "
        "block rather than a bad key. Try a VPN, or set HTTPS_PROXY in .env, then "
        "restart the server."
    )


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
