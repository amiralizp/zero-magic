"""Model provider primitives.

A provider's only job is to return a validated ``Breakdown`` plus usage. Retries,
fallback, persistence and rate limits live in the service, not in providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...schemas.prds import Breakdown


class ProviderError(RuntimeError):
    """A provider call failed. The service may try the next model."""


@dataclass
class ProviderOutput:
    breakdown: Breakdown
    input_tokens: int
    output_tokens: int
    latency_ms: float


class BreakdownProvider(Protocol):
    name: str

    async def generate(
        self,
        *,
        title: str,
        body: str,
        system_prompt: str,
        prompt_version: str,
        temperature: float = 0.0,
    ) -> ProviderOutput: ...
