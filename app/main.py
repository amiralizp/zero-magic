"""Application factory.

``uvicorn app.main:app`` uses the module-level app. Tests call ``create_app``
with their own settings and provider overrides, so limits and failures can be
exercised without touching environment variables.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .ai.providers.base import BreakdownProvider
from .ai.registry import ProviderRegistry, build_providers
from .api import cards, meta
from .config import Settings
from .errors import install_error_handlers
from .rate_limit import SlidingWindowLimiter
from .store import InMemoryStore


def create_app(
    *,
    settings: Settings | None = None,
    store: InMemoryStore | None = None,
    provider_overrides: Mapping[str, BreakdownProvider] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or InMemoryStore()

    providers = build_providers(settings)
    if provider_overrides:
        providers.update(provider_overrides)
    registry = ProviderRegistry(
        providers,
        primary=settings.primary_model,
        fallback=settings.fallback_model,
    )

    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description=(
            "The agentic development funnel, weeks 1-3: cards, comments, "
            "assignment, the stage machine, and PRD-to-cards breakdown with evals."
        ),
    )
    app.state.settings = settings
    app.state.store = store
    app.state.registry = registry
    app.state.limiter = SlidingWindowLimiter(
        limit=settings.breakdown_rate_limit,
        window_seconds=settings.breakdown_rate_window_seconds,
    )

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Actor-Id", "X-Request-Id"],
        expose_headers=["Retry-After", "X-Request-Id"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("X-Request-Id")
        request_id = incoming[:64] if incoming else uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    app.include_router(meta.router)
    app.include_router(cards.router)

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": settings.app_name,
                "version": settings.api_version,
                "docs": "/docs",
                "health": "/api/v1/health",
            }
        )

    return app


app = create_app()
