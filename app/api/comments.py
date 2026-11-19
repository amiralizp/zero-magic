"""Comments on cards. Built test-first from ``specs/card-02-comments.md``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from ..presenters import comment_to_read
from ..schemas.actors import Actor
from ..schemas.cards import CommentCreate, CommentList, CommentRead
from ..schemas.common import ErrorEnvelope
from ..services import cards as card_service
from ..repositories.factory import Repository
from .deps import get_store, require_actor

router = APIRouter(prefix="/api/v1/cards", tags=["comments"])

_ERRORS = {
    401: {"model": ErrorEnvelope, "description": "Missing or unknown actor."},
    404: {"model": ErrorEnvelope, "description": "Card not found."},
    422: {"model": ErrorEnvelope, "description": "Invalid payload."},
}


@router.get(
    "/{card_id}/comments",
    response_model=CommentList,
    responses={404: _ERRORS[404]},
    summary="List a card's comments, oldest first",
)
async def list_comments(
    card_id: str,
    store: Annotated[Repository, Depends(get_store)],
) -> CommentList:
    records = card_service.list_comments(store, card_id)
    return CommentList(
        items=[comment_to_read(store, record) for record in records],
        total=len(records),
    )


@router.post(
    "/{card_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Add a comment as a human or an agent",
)
async def add_comment(
    card_id: str,
    payload: CommentCreate,
    actor: Annotated[Actor, Depends(require_actor)],
    store: Annotated[Repository, Depends(get_store)],
) -> CommentRead:
    record = card_service.add_comment(store, actor, card_id, payload.body)
    return comment_to_read(store, record)
