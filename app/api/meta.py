"""Health, actors and the machine-readable funnel description."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..ai.prompts import PROMPTS
from ..ai.registry import ProviderRegistry
from ..config import Settings
from ..schemas.actors import Actor, ActorList
from ..schemas.cards import STAGE_ORDER
from ..services import cards as card_service
from ..services.cards import ALLOWED_TRANSITIONS, HUMAN_ONLY_TRANSITIONS
from ..repositories.factory import Repository
from .deps import get_registry, get_settings, get_store, require_actor

router = APIRouter(prefix="/api/v1", tags=["meta"])


@router.get("/health", summary="Liveness")
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[Repository, Depends(get_store)],
) -> dict[str, str]:
    return {
        "status": "ok",
        "version": settings.api_version,
        "environment": settings.environment,
        "storage": store.kind,
    }


@router.get("/actors", response_model=ActorList, summary="List seeded actors")
async def actors(
    store: Annotated[Repository, Depends(get_store)],
    actor: Annotated[Actor, Depends(require_actor)],
) -> ActorList:
    items = card_service.list_actors(store)
    return ActorList(items=items, total=len(items))


@router.get("/meta", summary="Stages, transitions and configured models")
async def meta(
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    actor: Annotated[Actor, Depends(require_actor)],
) -> dict[str, object]:
    return {
        "stages": [stage.value for stage in STAGE_ORDER],
        "transitions": {
            stage.value: sorted(target.value for target in ALLOWED_TRANSITIONS[stage])
            for stage in STAGE_ORDER
        },
        "human_only_transitions": [
            [source.value, target.value]
            for source, target in sorted(
                HUMAN_ONLY_TRANSITIONS,
                key=lambda pair: (pair[0].value, pair[1].value),
            )
        ],
        "models": registry.names,
        "default_models": [settings.primary_model, settings.fallback_model],
        "prompt_versions": sorted(PROMPTS),
        "limits": {
            "breakdown_timeout_seconds": settings.breakdown_timeout_seconds,
            "breakdown_rate_limit": settings.breakdown_rate_limit,
            "breakdown_rate_window_seconds": settings.breakdown_rate_window_seconds,
            "max_prd_chars": settings.max_prd_chars,
            "max_cards_per_breakdown": settings.max_cards_per_breakdown,
        },
    }
