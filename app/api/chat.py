"""Chat: a model list and an SSE completion stream.

The stream speaks the same ``data:`` frames the OpenAI-compatible endpoint does
so the browser can append deltas as they arrive. Errors travel as an
``{"error": ...}`` frame because the response has already started by then.

The provider is whatever ``CHAT_BASE_URL`` points at; DeepSeek by default. The
route never names a provider in its error codes, so swapping vendors is a config
change rather than an API change.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..ai.chat.client import ChatAuthError, ChatBlockedError, ChatClient, ChatUpstreamError
from ..config import Settings
from ..errors import AppError
from ..schemas.actors import Actor
from ..schemas.chat import ChatCompletionRequest
from ..schemas.common import ErrorEnvelope
from ..services import chat as chat_policy
from ..services.chat_agent import prepare_messages, run_agent
from ..repositories.factory import Repository
from .deps import get_settings, get_store, require_actor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_ERRORS = {
    400: {"model": ErrorEnvelope, "description": "Bad request."},
    401: {"model": ErrorEnvelope, "description": "Missing or rejected API key."},
    502: {"model": ErrorEnvelope, "description": "Upstream error."},
}


def _error_frame(message: str) -> str:
    return f"data: {json.dumps({'error': message})}\n\n"


@router.get("/models", responses=_ERRORS)
async def list_models(
    settings: Annotated[Settings, Depends(get_settings)],
    actor: Annotated[Actor, Depends(require_actor)],
) -> dict[str, Any]:
    chat_policy.require_chat_key(settings)
    client = ChatClient(settings)
    try:
        models = await client.list_models()
    except ChatAuthError as exc:
        raise AppError(status_code=401, code="chat_key_rejected", message=chat_policy.key_hint(settings)) from exc
    except ChatBlockedError as exc:
        raise AppError(status_code=502, code="chat_blocked", message=chat_policy.blocked_hint(settings)) from exc
    except ChatUpstreamError as exc:
        raise AppError(
            status_code=502,
            code="chat_unreachable",
            message=f"Could not reach {settings.chat_provider}: {exc.kind}.",
        ) from exc
    return {"models": models, "default": settings.chat_model}


@router.post("/completions", responses=_ERRORS)
async def chat_completions(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[Repository, Depends(get_store)],
    actor: Annotated[Actor, Depends(require_actor)],
) -> StreamingResponse:
    try:
        raw = await request.json()
    except json.JSONDecodeError as exc:
        raise AppError(
            status_code=400,
            code="invalid_json",
            message="The request body must be valid JSON.",
        ) from exc
    if not isinstance(raw, dict):
        raise AppError(
            status_code=400,
            code="invalid_body",
            message="The request body must be a JSON object.",
        )
    try:
        body = ChatCompletionRequest.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - surfaced as invalid_payload
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            details = [
                {
                    "location": [str(part) for part in err.get("loc", ())],
                    "message": err.get("msg", "Invalid value"),
                    "type": err.get("type", "value_error"),
                }
                for err in exc.errors()
            ]
        else:
            details = None
        raise AppError(
            status_code=422,
            code="invalid_payload",
            message="Request payload is invalid. See details for the failing fields.",
            details=details,
        ) from exc
    messages = body.messages or []
    if not isinstance(messages, list) or not messages:
        raise AppError(
            status_code=400,
            code="invalid_messages",
            message="messages must be a non-empty list of {role, content} objects.",
        )

    model = body.model or settings.chat_model
    temperature = body.temperature
    max_tokens = body.max_tokens

    chat_policy.require_chat_key(settings)

    client = ChatClient(settings)
    prepared = prepare_messages(messages, store, actor)

    async def event_generator():
        try:
            async for event in run_agent(
                client.complete,
                store,
                actor,
                prepared,
                settings=settings,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if event["type"] == "tool":
                    yield f"data: {json.dumps({'gantry_tool': event['tool']})}\n\n"
                else:
                    chunk = {"choices": [{"delta": {"content": event["text"]}}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        except ChatUpstreamError as exc:
            status = exc.status
            logger.warning(
                "chat upstream error code=chat_upstream_error status=%s kind=%s",
                status,
                exc.kind,
            )
            if status is not None:
                hint = chat_policy.upstream_hint(settings, status)
                if hint is not None:
                    yield _error_frame(hint)
                    return
            yield _error_frame("chat_upstream_error: the chat provider request failed")
        except Exception as exc:  # noqa: BLE001 - surfaced to the browser as a frame
            logger.warning(
                "chat error code=chat_internal_error type=%s", exc.__class__.__name__
            )
            yield _error_frame("chat_internal_error: the chat request failed")

    return StreamingResponse(event_generator(), media_type="text/event-stream")
