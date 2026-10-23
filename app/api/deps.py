"""FastAPI dependencies: settings, store, actor identity and limits."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from ..ai.registry import ProviderRegistry
from ..config import Settings
from ..errors import AppError
from ..rate_limit import SlidingWindowLimiter
from ..schemas.actors import Actor, ActorRole
from ..services.breakdown import BreakdownService
from ..store import InMemoryStore


def get_store(request: Request) -> InMemoryStore:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.limiter


def optional_actor(
    store: Annotated[InMemoryStore, Depends(get_store)],
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
) -> Actor | None:
    if x_actor_id is None:
        return None
    actor = store.get_actor(x_actor_id)
    if actor is None:
        raise AppError(
            401,
            "unknown_actor",
            f"Actor {x_actor_id!r} is not registered.",
            headers={"WWW-Authenticate": "Actor"},
        )
    return actor


def require_actor(
    actor: Annotated[Actor | None, Depends(optional_actor)],
) -> Actor:
    if actor is None:
        raise AppError(
            401,
            "missing_actor",
            "Send X-Actor-Id with a registered human or agent id.",
            headers={"WWW-Authenticate": "Actor"},
        )
    return actor


def require_human(
    actor: Annotated[Actor, Depends(require_actor)],
) -> Actor:
    if actor.role is not ActorRole.HUMAN:
        raise AppError(
            403,
            "human_only",
            "This action requires a human actor. Agents may comment and build.",
        )
    return actor


def get_breakdown_service(
    store: Annotated[InMemoryStore, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_limiter)],
) -> BreakdownService:
    return BreakdownService(store, settings, registry, limiter)
