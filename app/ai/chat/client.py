"""A thin client for an OpenAI-compatible chat API.

DeepSeek is the default provider, but the base URL, key and model all come from
settings, so pointing Gantry at another OpenAI-compatible vendor (or a local
gateway) needs no code change.

Why not an SDK: the app needs two calls and no dependency growth. httpx is
already a runtime dependency, and the streaming frames are passed through
unchanged so the browser can render deltas as they arrive.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from ...config import Settings
from .errors import ChatUpstreamError

DEFAULT_TIMEOUT = 30.0
STREAM_TIMEOUT = 300.0


class ChatAuthError(RuntimeError):
    """The API key is missing, revoked or not allowed to use this model."""


class ChatBlockedError(RuntimeError):
    """The request was refused before auth: a network or region block."""


def _to_upstream_error(exc: httpx.HTTPError) -> "ChatUpstreamError":
    from .errors import ChatUpstreamError

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            detail = exc.response.text[:400]
        except Exception:  # noqa: BLE001 - best effort
            detail = ""
        return ChatUpstreamError(status=status, kind="http_status", detail=detail)
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return ChatUpstreamError(status=None, kind="timeout", detail=str(exc))
    if isinstance(exc, httpx.ConnectError):
        return ChatUpstreamError(status=None, kind="connection", detail=str(exc))
    return ChatUpstreamError(status=None, kind="connection", detail=str(exc))


class ChatClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.chat_base_url.rstrip("/")
        self.models_url = (settings.chat_models_url or f"{self.base_url}/models").rstrip("/")
        self.api_key = settings.chat_api_key
        self.provider = settings.chat_provider
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # OpenCode Go refuses a completion that has no session id. Other
        # providers ignore the header, so it is only sent when configured.
        if settings.chat_session:
            self.headers["x-opencode-session"] = settings.chat_session
        self.default_model = settings.chat_model

    async def list_models(self) -> list[str]:
        """Return the model ids this key can actually use.

        A rejected key must surface as an error, not as a believable-looking
        hardcoded list: an invented menu hides the real problem until the first
        message fails.
        """
        if not self.api_key:
            raise ChatAuthError(f"CHAT_API_KEY for {self.provider} is not configured.")
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.get(self.models_url, headers=self.headers)
                if response.status_code == 401:
                    raise ChatAuthError(f"{self.provider} rejected CHAT_API_KEY.")
                if response.status_code == 403:
                    raise ChatBlockedError(f"{self.provider} returned 403 Forbidden.")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise _to_upstream_error(exc) from exc
        models = sorted(entry["id"] for entry in data.get("data", []) if "id" in entry)
        return models or [self.default_model]

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """One non-streaming turn, including any tool calls the model requested."""

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise _to_upstream_error(exc) from exc
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise RuntimeError(f"{self.provider} returned no completion.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError(f"{self.provider} returned no message.")
        return message

    async def chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[dict[str, Any], None]:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[len("data: ") :]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue
