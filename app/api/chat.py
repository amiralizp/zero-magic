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
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..ai.chat.client import ChatAuthError, ChatBlockedError, ChatClient
from ..config import Settings
from ..errors import AppError
from ..schemas.actors import Actor
from ..schemas.chat import ChatCompletionRequest
from ..schemas.common import ErrorEnvelope
from ..services import chat as chat_policy
from ..services.chat_agent import prepare_messages, run_agent
from ..db import Store
from .deps import get_settings, get_store, optional_actor

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_ERRORS = {
    400: {"model": ErrorEnvelope, "description": "Bad request."},
    401: {"model": ErrorEnvelope, "description": "Missing or rejected API key."},
    502: {"model": ErrorEnvelope, "description": "Upstream error."},
}


def _key_hint(settings: Settings) -> str:
    return (
        f"{settings.chat_provider} rejected the API key. Check CHAT_API_KEY in .env "
        "and restart the server."
    )


def _blocked_hint(settings: Settings) -> str:
    return (
        f"{settings.chat_provider} answered 403 Forbidden. That is often a network "
        "block rather than a bad key. Try a VPN, or set HTTPS_PROXY in .env, then "
        "restart the server."
    )


def _error_frame(message: str) -> str:
    return f"data: {json.dumps({'error': message})}\n\n"


@router.get("/models", responses=_ERRORS)
async def list_models(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    chat_policy.require_chat_key(settings)
    client = ChatClient(settings)
    try:
        models = await client.list_models()
    except ChatAuthError as exc:
        raise AppError(status_code=401, code="chat_key_rejected", message=_key_hint(settings)) from exc
    except ChatBlockedError as exc:
        raise AppError(status_code=502, code="chat_blocked", message=_blocked_hint(settings)) from exc
    except httpx.HTTPError as exc:
        raise AppError(
            status_code=502,
            code="chat_unreachable",
            message=f"Could not reach {settings.chat_provider}: {exc.__class__.__name__}.",
        ) from exc
    return {"models": models, "default": settings.chat_model}


@router.post("/completions", responses=_ERRORS)
async def chat_completions(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[Store, Depends(get_store)],
    actor: Annotated[Actor | None, Depends(optional_actor)],
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

    # A browser that still runs an older console script sends no header. The
    # body is the same trust level (there is no login yet), so accept it too.
    actor = chat_policy.resolve_actor(store, actor, body.actor)

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
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            hint = chat_policy.upstream_hint(settings, status)
            if hint is not None:
                yield _error_frame(hint)
                return
            # The body of a streaming error response is not read yet.
            detail = await exc.response.aread()
            text = detail.decode("utf-8", "replace")[:400]
            yield _error_frame(f"{settings.chat_provider} error {status}: {text}")
        except Exception as exc:  # noqa: BLE001 - surfaced to the browser as a frame
            yield _error_frame(str(exc) or exc.__class__.__name__)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
