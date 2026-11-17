"""Card endpoints: create, list, read, edit, delete, transition."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from ..db import Store
from ..presenters import card_to_read
from ..schemas.actors import Actor
from ..schemas.cards import (
    CardCreate,
    CardList,
    CardRead,
    CardUpdate,
    Stage,
    TransitionRequest,
)
from ..schemas.common import ErrorEnvelope
from ..services import cards as card_service
from .deps import get_store, require_actor, require_human

router = APIRouter(prefix="/api/v1", tags=["cards"])

_ERRORS = {
    401: {"model": ErrorEnvelope, "description": "Missing or unknown actor."},
    403: {"model": ErrorEnvelope, "description": "Actor may not perform this action."},
    404: {"model": ErrorEnvelope, "description": "Card not found."},
    409: {"model": ErrorEnvelope, "description": "Illegal transition or locked spec."},
    422: {"model": ErrorEnvelope, "description": "Invalid payload."},
}


@router.post(
    "/cards",
    response_model=CardRead,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Create a card in the Spec stage",
)
async def create_card(
    payload: CardCreate,
    actor: Annotated[Actor, Depends(require_human)],
    store: Annotated[Store, Depends(get_store)],
) -> CardRead:
    record = card_service.create_card(store, actor, payload)
    return card_to_read(store, record)


@router.get("/cards", response_model=CardList, summary="List and filter cards")
async def list_cards(
    store: Annotated[Store, Depends(get_store)],
    stage: Stage | None = None,
    assignee: str | None = Query(default=None, description="Actor id"),
    q: str | None = Query(default=None, max_length=100, description="Title/goal text"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CardList:
    records, total = card_service.list_cards(
        store, stage=stage, assignee_id=assignee, query=q, limit=limit, offset=offset
    )
    return CardList(
        items=[card_to_read(store, record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/cards/{card_id}",
    response_model=CardRead,
    responses={404: _ERRORS[404]},
    summary="Read one card",
)
async def get_card(
    card_id: str,
    store: Annotated[Store, Depends(get_store)],
) -> CardRead:
    record = card_service.get_card_or_404(store, card_id)
    return card_to_read(store, record)


@router.patch(
    "/cards/{card_id}",
    response_model=CardRead,
    responses={**_ERRORS, 409: _ERRORS[409]},
    summary="Edit a card spec while it is in Spec",
)
async def update_card(
    card_id: str,
    payload: CardUpdate,
    actor: Annotated[Actor, Depends(require_human)],
    store: Annotated[Store, Depends(get_store)],
) -> CardRead:
    record = card_service.update_spec(store, actor, card_id, payload)
    return card_to_read(store, record)


@router.delete(
    "/cards/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_ERRORS, 204: {"description": "Card deleted"}},
    summary="Delete a card",
)
async def delete_card(
    card_id: str,
    actor: Annotated[Actor, Depends(require_human)],
    store: Annotated[Store, Depends(get_store)],
) -> Response:
    card_service.delete_card(store, actor, card_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/cards/{card_id}/transition",
    response_model=CardRead,
    responses=_ERRORS,
    summary="Move a card along a legal funnel edge",
)
async def transition_card(
    card_id: str,
    payload: TransitionRequest,
    actor: Annotated[Actor, Depends(require_actor)],
    store: Annotated[Store, Depends(get_store)],
) -> CardRead:
    record = card_service.transition_card(store, actor, card_id, payload)
    return card_to_read(store, record)
