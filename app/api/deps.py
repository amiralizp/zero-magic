"""FastAPI dependencies: settings, store, token identity, actors and limits.

Authentication ("who are you?") happens here: a signed bearer token is turned
into a token identity and then into a seeded actor. Authorization ("what may
you do?") stays in the service layer. A legacy identity header is deliberately
not read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..ai.registry import ProviderRegistry
from ..config import Settings
from ..errors import AppError
from ..rate_limit import SlidingWindowLimiter
from ..repositories.factory import Repository
from ..schemas.actors import Actor, ActorRole
from ..services.auth import TokenIdentity, decode_token
from ..services.breakdown import BreakdownService


def get_store(request: Request) -> Repository:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.limiter


def get_token_identity(request: Request) -> TokenIdentity:
    """Verify the Authorization header and return the claimed identity."""

    header = request.headers.get("Authorization")
    if not header:
        raise AppError(
            401,
            "missing_token",
            "Send Authorization: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(
            401,
            "invalid_token",
            "Authorization must use the Bearer scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings(request)
    return decode_token(token.strip(), settings.jwt_secret)


def require_actor(
    identity: Annotated[TokenIdentity, Depends(get_token_identity)],
    store: Annotated[Repository, Depends(get_store)],
) -> Actor:
    actor = store.get_actor(identity.actor_id)
    if actor is None:
        raise AppError(
            401,
            "invalid_token",
            "The token names an unknown actor.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # The store is authoritative: a signed token cannot claim a role the actor
    # does not actually have. Mismatches are an authentication failure, not 403.
    if identity.role is not actor.role:
        raise AppError(
            401,
            "invalid_token",
            "The token's role does not match the actor.",
            headers={"WWW-Authenticate": "Bearer"},
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
    store: Annotated[Repository, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_limiter)],
) -> BreakdownService:
    return BreakdownService(store, settings, registry, limiter)
