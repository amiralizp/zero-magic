"""Application factory.

``uvicorn app.main:app`` uses the module-level app. Tests call ``create_app``
with their own settings and provider overrides, so limits and failures can be
exercised without touching environment variables.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai.providers.base import BreakdownProvider
from .ai.registry import ProviderRegistry, build_providers
from .api import assignment, cards, comments, meta, ops, prds, chat
from .config import Settings
from .db import Store, build_store
from .errors import install_error_handlers
from .rate_limit import SlidingWindowLimiter

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(
    *,
    settings: Settings | None = None,
    store: Store | None = None,
    provider_overrides: Mapping[str, BreakdownProvider] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or build_store(settings)

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

    @app.middleware("http")
    async def fresh_console(request: Request, call_next):  # type: ignore[no-untyped-def]
        """The console is edited in place; a stale cached script hides fixes."""

        response = await call_next(request)
        path = request.url.path
        if path == "/console" or path.startswith("/console/assets/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(meta.router)
    app.include_router(cards.router)
    app.include_router(comments.router)
    app.include_router(assignment.router)
    app.include_router(prds.router)
    app.include_router(chat.router)
    app.include_router(ops.router)

    app.mount(
        "/console/assets",
        StaticFiles(directory=WEB_DIR),
        name="console-assets",
    )

    app.mount(
        "/chat/assets",
        StaticFiles(directory=WEB_DIR / "chat"),
        name="chat-assets",
    )

    @app.get("/console", include_in_schema=False)
    async def console() -> FileResponse:
        """A small, build-free console so the API can be used by hand."""
        return FileResponse(WEB_DIR / "console.html")

    @app.get("/chat", include_in_schema=False)
    async def chat_page() -> FileResponse:
        """Gantry AI chat powered by the configured provider."""
        return FileResponse(WEB_DIR / "chat" / "index.html")

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": settings.app_name,
                "version": settings.api_version,
                "docs": "/docs",
                "console": "/console",
                "chat": "/chat",
                "health": "/api/v1/health",
            }
        )

    return app


app = create_app()
