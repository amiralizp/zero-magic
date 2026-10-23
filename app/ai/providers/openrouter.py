"""OpenAI-compatible chat provider (OpenRouter by default).

We ask for a JSON object, validate it with the same Pydantic models as the
mock, and let the service decide whether to retry or fall back. No SDK is
required, which keeps the dependency surface small and the call visible.
"""

from __future__ import annotations

import json
import time

import httpx

from ...schemas.prds import Breakdown
from ..tokens import estimate_tokens
from .base import ProviderError, ProviderOutput


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _extract_json_object(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ProviderError("Model returned no JSON object.")
    return cleaned[start : end + 1]


class OpenRouterProvider:
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def generate(
        self,
        *,
        title: str,
        body: str,
        system_prompt: str,
        prompt_version: str,
        temperature: float = 0.0,
    ) -> ProviderOutput:
        started = time.perf_counter()
        payload = {
            "model": self.name,
            "temperature": temperature,
            "max_tokens": 2500,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"<prd>\n<title>{title}</title>\n{body}\n</prd>\n"
                        "Return the JSON object now."
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": "Zero Magic Funnel",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error calling {self.name}.") from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} returned HTTP {response.status_code}."
            )
        try:
            data = response.json()
            choice = data["choices"][0]
            content = _content_to_text(choice["message"].get("content"))
            breakdown = Breakdown.model_validate_json(_extract_json_object(content))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{self.name} returned unusable output.") from exc

        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or estimate_tokens(system_prompt + body))
        output_tokens = int(usage.get("completion_tokens") or estimate_tokens(content))
        return ProviderOutput(
            breakdown=breakdown,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
