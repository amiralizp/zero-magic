"""Business rules for cards: who may do what, and which moves are legal."""

from __future__ import annotations

from ..config import Settings
from ..db import Store
from ..domain_errors import AppError
from ..schemas.actors import Actor, ActorRole
from ..schemas.cards import CardCreate, CardUpdate, Stage, TransitionRequest
from ..records import CardRecord, CommentRecord, PRDRecord

# The funnel's legal edges. Everything else is a 409, not a silent correction.
ALLOWED_TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    Stage.SPEC: frozenset({Stage.READY}),
    Stage.READY: frozenset({Stage.SPEC, Stage.BUILDING}),
    Stage.BUILDING: frozenset({Stage.CHECKS}),
    Stage.CHECKS: frozenset({Stage.VALIDATION, Stage.BUILDING}),
    Stage.VALIDATION: frozenset({Stage.DONE, Stage.BUILDING}),
    Stage.DONE: frozenset(),
}

# Edges only a human may take. Approving a spec, accepting the checks and
# passing validation are the moments where responsibility cannot be delegated
# to an agent. Agents may claim work and submit it for checks; they may not
# validate it.
HUMAN_ONLY_TRANSITIONS: frozenset[tuple[Stage, Stage]] = frozenset(
    {
        (Stage.SPEC, Stage.READY),
        (Stage.READY, Stage.SPEC),
        (Stage.CHECKS, Stage.VALIDATION),
        (Stage.CHECKS, Stage.BUILDING),
        (Stage.VALIDATION, Stage.BUILDING),
        (Stage.VALIDATION, Stage.DONE),
    }
)


def get_card_or_404(store: Store, card_id: str) -> CardRecord:
    card = store.get_card(card_id)
    if card is None:
        raise AppError(404, "card_not_found", f"Card {card_id!r} does not exist.")
    return card


# Backwards-compatible alias for internal callers.
_card_or_404 = get_card_or_404


def list_cards(
    store: Store,
    *,
    stage: Stage | None = None,
    assignee_id: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CardRecord], int]:
    records = store.list_cards(stage=stage, assignee_id=assignee_id, query=query)
    total = len(records)
    window = records[offset : offset + limit]
    return window, total


def list_prds(store: Store) -> list[PRDRecord]:
    return store.list_prds()


def _require_human(actor: Actor, action: str) -> None:
    if actor.role is not ActorRole.HUMAN:
        raise AppError(
            403,
            "human_only",
            f"Only a human may {action}.",
        )


def _ensure_assignee(store: Store, assignee_id: str | None) -> None:
    if assignee_id is not None and store.get_actor(assignee_id) is None:
        raise AppError(
            422,
            "unknown_assignee",
            f"Assignee {assignee_id!r} is not a known actor.",
        )


def create_card(
    store: Store, actor: Actor, payload: CardCreate
) -> CardRecord:
    _require_human(actor, "create a card")
    _ensure_assignee(store, payload.assignee_id)
    return store.create_card(
        title=payload.title,
        goal=payload.goal,
        acceptance_criteria=payload.acceptance_criteria,
        out_of_scope=payload.out_of_scope,
        created_by=actor.id,
        assignee_id=payload.assignee_id,
    )


def update_spec(
    store: Store, actor: Actor, card_id: str, payload: CardUpdate
) -> CardRecord:
    _require_human(actor, "edit a card spec")
    card = _card_or_404(store, card_id)
    if card.stage is not Stage.SPEC:
        raise AppError(
            409,
            "spec_locked",
            "The spec can only be edited while the card is in Spec.",
            details={"stage": card.stage.value},
        )
    changes = payload.model_dump(exclude_none=True)
    return store.update_card(card_id, actor_id=actor.id, **changes)


def delete_card(store: Store, actor: Actor, card_id: str) -> None:
    _require_human(actor, "delete a card")
    _card_or_404(store, card_id)
    store.delete_card(card_id)
    store.audit("card.deleted", card_id, actor.id)


def transition_card(
    store: Store,
    actor: Actor,
    card_id: str,
    payload: TransitionRequest,
) -> CardRecord:
    card = _card_or_404(store, card_id)
    target = payload.to_stage

    if target is card.stage:
        raise AppError(
            409,
            "illegal_transition",
            f"Card is already in {card.stage.value}.",
            details={"stage": card.stage.value},
        )

    allowed = ALLOWED_TRANSITIONS[card.stage]
    if target not in allowed:
        raise AppError(
            409,
            "illegal_transition",
            f"Cannot move a card from {card.stage.value} to {target.value}.",
            details={
                "current_stage": card.stage.value,
                "requested_stage": target.value,
                "allowed": sorted(stage.value for stage in allowed),
            },
        )

    if actor.role is ActorRole.AGENT:
        if (card.stage, target) in HUMAN_ONLY_TRANSITIONS:
            raise AppError(
                403,
                "agent_not_allowed",
                f"An agent may not move a card from {card.stage.value} to {target.value}.",
                details={"current_stage": card.stage.value, "requested_stage": target.value},
            )
        if card.assignee_id is not None and card.assignee_id != actor.id:
            raise AppError(
                403,
                "not_assignee",
                "An agent may only work on a card assigned to it.",
                details={"assignee_id": card.assignee_id},
            )

    if target is Stage.DONE and card.built_by == actor.id:
        raise AppError(
            403,
            "self_validation_blocked",
            "The actor that built this card cannot be the one that validates it.",
        )

    changes: dict[str, object] = {"stage": target}
    if target is Stage.BUILDING:
        changes["built_by"] = actor.id
        if card.assignee_id is None:
            changes["assignee_id"] = actor.id
    updated = store.update_card(card_id, actor_id=actor.id, **changes)
    store.audit(
        "card.transitioned",
        card_id,
        actor.id,
        {
            "from": card.stage.value,
            "to": target.value,
            "note": payload.note,
            "assignee_id": updated.assignee_id,
        },
    )
    return updated


def assign_card(
    store: Store, actor: Actor, card_id: str, assignee_id: str | None
) -> CardRecord:
    _require_human(actor, "assign a card")
    card = _card_or_404(store, card_id)
    if card.stage is Stage.DONE:
        raise AppError(
            409,
            "card_closed",
            "A card in Done cannot be reassigned.",
        )
    _ensure_assignee(store, assignee_id)
    updated = store.update_card(card_id, actor_id=actor.id, assignee_id=assignee_id)
    store.audit(
        "card.assigned",
        card_id,
        actor.id,
        {"from": card.assignee_id, "to": assignee_id},
    )
    return updated


def add_comment(
    store: Store, actor: Actor, card_id: str, body: str
) -> CommentRecord:
    _card_or_404(store, card_id)
    return store.create_comment(card_id=card_id, author_id=actor.id, body=body)


def list_comments(store: Store, card_id: str) -> list[CommentRecord]:
    _card_or_404(store, card_id)
    return store.list_comments(card_id)


def create_prd(
    store: Store, settings: Settings, actor: Actor, *, title: str, body: str
) -> PRDRecord:
    _require_human(actor, "create a PRD")
    if len(body) > settings.max_prd_chars:
        raise AppError(
            422,
            "prd_too_large",
            f"PRD body exceeds the {settings.max_prd_chars} character limit.",
            details={"length": len(body), "limit": settings.max_prd_chars},
        )
    return store.create_prd(title=title, body=body, created_by=actor.id)


def get_prd_or_404(store: Store, prd_id: str) -> PRDRecord:
    prd = store.get_prd(prd_id)
    if prd is None:
        raise AppError(404, "prd_not_found", f"PRD {prd_id!r} does not exist.")
    return prd
