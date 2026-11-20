"""Login and current-identity endpoints.

Authentication answers "who are you?" here. Authorization stays in services.
The only identity input is a signed token; a legacy identity header is not read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import Settings
from ..repositories.factory import Repository
from ..schemas.actors import Actor
from ..schemas.auth import LoginRequest, LoginResponse, MeResponse
from ..schemas.common import ErrorEnvelope
from ..services import auth as auth_service
from .deps import get_settings, get_store, get_token_identity, require_actor

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_UNAUTHORIZED = {
    401: {
        "model": ErrorEnvelope,
        "description": "Invalid credentials or missing/invalid token.",
    }
}


@router.post(
    "/login",
    response_model=LoginResponse,
    responses=_UNAUTHORIZED,
    summary="Exchange credentials for a signed token",
)
async def login(
    payload: LoginRequest,
    store: Annotated[Repository, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    token = auth_service.authenticate(
        store,
        payload.username,
        payload.password,
        secret=settings.jwt_secret,
        ttl_seconds=settings.token_ttl_seconds,
    )
    return LoginResponse(access_token=token, expires_in=settings.token_ttl_seconds)


@router.get(
    "/me",
    response_model=MeResponse,
    responses=_UNAUTHORIZED,
    summary="Describe the token's caller",
)
async def me(
    identity: Annotated[auth_service.TokenIdentity, Depends(get_token_identity)],
    actor: Annotated[Actor, Depends(require_actor)],
) -> MeResponse:
    return MeResponse(
        actor_id=actor.id,
        username=identity.username,
        role=actor.role,
        display_name=actor.display_name,
    )
