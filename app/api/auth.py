"""Login and current-identity endpoints.

Authentication answers "who are you?" here. Authorization stays in services.
The only identity input is a signed token; a legacy identity header is not read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..config import Settings
from ..errors import AppError
from ..rate_limit import SlidingWindowLimiter
from ..repositories.factory import Repository
from ..schemas.actors import Actor
from ..schemas.auth import LoginRequest, LoginResponse, MeResponse
from ..schemas.common import ErrorEnvelope
from ..services import auth as auth_service
from .deps import (
    get_login_ip_limiter,
    get_login_limiter,
    get_settings,
    get_store,
    get_token_identity,
    require_actor,
)

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
    request: Request,
    payload: LoginRequest,
    store: Annotated[Repository, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    ip_limiter: Annotated[SlidingWindowLimiter, Depends(get_login_ip_limiter)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_login_limiter)],
) -> LoginResponse:
    client_host = request.client.host if request.client else "unknown"
    username = payload.username.lower()
    # SlidingWindowLimiter has no peek; both checks count all attempts.
    ip_retry = ip_limiter.hit(f"login:ip:{client_host}")
    user_retry = limiter.hit(f"login:user-ip:{username}:{client_host}")
    retry_after = max(
        (value for value in (ip_retry, user_retry) if value is not None),
        default=None,
    )
    if retry_after is not None:
        seconds = max(1, int(retry_after) + 1)
        if ip_retry is not None:
            details = {
                "limit": settings.login_ip_rate_limit,
                "window_seconds": settings.login_ip_rate_window_seconds,
            }
        else:
            details = {
                "limit": settings.login_rate_limit,
                "window_seconds": settings.login_rate_window_seconds,
            }
        raise AppError(
            429,
            "rate_limited",
            "Too many login attempts. Try again later.",
            details=details,
            headers={"Retry-After": str(seconds)},
        )
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
    store: Annotated[Repository, Depends(get_store)],
    actor: Annotated[Actor, Depends(require_actor)],
) -> MeResponse:
    user = store.get_user_by_actor_id(actor.id)
    username = user.username if user is not None else actor.id
    return MeResponse(
        actor_id=actor.id,
        username=username,
        role=actor.role,
        display_name=actor.display_name,
    )
