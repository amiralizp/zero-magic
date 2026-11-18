"""PRD endpoints, including the week-3 breakdown call."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from ..config import Settings
from ..presenters import card_to_read, prd_to_read
from ..schemas.actors import Actor
from ..schemas.common import ErrorEnvelope
from ..schemas.prds import (
    BreakdownRead,
    BreakdownRequest,
    PRDCreate,
    PRDList,
    PRDRead,
)
from ..services import cards as card_service
from ..services.breakdown import BreakdownService
from ..repositories.factory import Repository
from .deps import (
    get_breakdown_service,
    get_settings,
    get_store,
    require_human,
)

router = APIRouter(prefix="/api/v1", tags=["prds"])

_ERRORS = {
    401: {"model": ErrorEnvelope, "description": "Missing or unknown actor."},
    403: {"model": ErrorEnvelope, "description": "Only a human may do this."},
    404: {"model": ErrorEnvelope, "description": "PRD not found."},
    422: {"model": ErrorEnvelope, "description": "Invalid payload or model."},
    429: {"model": ErrorEnvelope, "description": "Breakdown rate limit reached."},
    502: {"model": ErrorEnvelope, "description": "All model attempts failed."},
    504: {"model": ErrorEnvelope, "description": "Model call timed out."},
}


@router.post(
    "/prds",
    response_model=PRDRead,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Store a PRD",
)
async def create_prd(
    payload: PRDCreate,
    actor: Annotated[Actor, Depends(require_human)],
    store: Annotated[Repository, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PRDRead:
    record = card_service.create_prd(
        store, settings, actor, title=payload.title, body=payload.body
    )
    return prd_to_read(store, record)


@router.get("/prds", response_model=PRDList, summary="List PRDs, newest first")
async def list_prds(
    store: Annotated[Repository, Depends(get_store)],
) -> PRDList:
    records = card_service.list_prds(store)
    return PRDList(
        items=[prd_to_read(store, record) for record in records],
        total=len(records),
    )


@router.get(
    "/prds/{prd_id}",
    response_model=PRDRead,
    responses={404: _ERRORS[404]},
    summary="Read a PRD",
)
async def get_prd(
    prd_id: str,
    store: Annotated[Repository, Depends(get_store)],
) -> PRDRead:
    record = card_service.get_prd_or_404(store, prd_id)
    return prd_to_read(store, record)


@router.post(
    "/prds/{prd_id}/breakdown",
    response_model=BreakdownRead,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Turn a PRD into typed draft cards in Spec",
)
async def breakdown_prd(
    prd_id: str,
    actor: Annotated[Actor, Depends(require_human)],
    service: Annotated[BreakdownService, Depends(get_breakdown_service)],
    store: Annotated[Repository, Depends(get_store)],
    payload: BreakdownRequest | None = None,
) -> BreakdownRead:
    result = await service.run(prd_id, actor, payload or BreakdownRequest())
    return BreakdownRead(
        prd_id=result.prd_id,
        cards=[card_to_read(store, card) for card in result.cards],
        model_used=result.model_used,
        fallback_used=result.fallback_used,
        prompt_version=result.prompt_version,
        attempts=result.attempts,
        usage=result.usage,
        duration_ms=result.duration_ms,
        warnings=result.warnings,
    )
