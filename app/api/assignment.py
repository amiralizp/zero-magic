"""Card assignment. Built test-first from ``specs/card-03-assignment.md``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..presenters import card_to_read
from ..schemas.actors import Actor
from ..schemas.cards import AssigneeUpdate, CardRead
from ..schemas.common import ErrorEnvelope
from ..services import cards as card_service
from ..db import Store
from .deps import get_store, require_human

router = APIRouter(prefix="/api/v1/cards", tags=["assignment"])

_ERRORS = {
    401: {"model": ErrorEnvelope, "description": "Missing or unknown actor."},
    403: {"model": ErrorEnvelope, "description": "Only a human may assign."},
    404: {"model": ErrorEnvelope, "description": "Card not found."},
    409: {"model": ErrorEnvelope, "description": "Card is closed."},
    422: {"model": ErrorEnvelope, "description": "Unknown assignee."},
}


@router.put(
    "/{card_id}/assignee",
    response_model=CardRead,
    responses=_ERRORS,
    summary="Set or clear the single assignee of a card",
)
async def set_assignee(
    card_id: str,
    payload: AssigneeUpdate,
    actor: Annotated[Actor, Depends(require_human)],
    store: Annotated[Store, Depends(get_store)],
) -> CardRead:
    record = card_service.assign_card(store, actor, card_id, payload.assignee_id)
    return card_to_read(store, record)
