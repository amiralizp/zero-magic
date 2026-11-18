"""PRD to draft cards: prompt, timeout, retries, fallback and persistence.

The endpoint is synchronous from the client's point of view, but the call is
awaited and bounded by a deadline. If every attempt fails we create no cards:
a partial breakdown is worse than a clean error.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from ..ai.prompts import PromptSpec, build_user_message, get_prompt
from ..ai.registry import ProviderRegistry
from ..ai.safety import neutralize, scan_injection
from ..ai.tokens import estimate_cost
from ..config import Settings
from ..domain_errors import AppError
from ..rate_limit import SlidingWindowLimiter
from ..schemas.actors import Actor, ActorRole
from ..schemas.prds import (
    Breakdown,
    BreakdownRead,
    BreakdownRequest,
    Usage,
)
from ..db import Store
from .cards import get_prd_or_404

_OUTPUT_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "you are now",
)


def _output_has_injection(breakdown: Breakdown) -> bool:
    for card in breakdown.cards:
        text = " ".join(
            [card.title, card.goal, *card.acceptance_criteria, *card.depends_on]
        ).casefold()
        if any(marker in text for marker in _OUTPUT_INJECTION_MARKERS):
            return True
    return False


def _validate_output(breakdown: Breakdown, max_cards: int) -> None:
    if len(breakdown.cards) > max_cards:
        raise ValueError(f"breakdown produced more than {max_cards} cards")
    if _output_has_injection(breakdown):
        raise ValueError("output echoed instruction-like text from the PRD")


@dataclass
class BreakdownResult:
    prd_id: str
    cards: list  # list[CardRecord]
    model_used: str
    fallback_used: bool
    prompt_version: str
    attempts: int
    usage: Usage
    duration_ms: int
    warnings: list[str]


class BreakdownService:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        registry: ProviderRegistry,
        limiter: SlidingWindowLimiter,
    ) -> None:
        self.store = store
        self.settings = settings
        self.registry = registry
        self.limiter = limiter

    async def run(
        self,
        prd_id: str,
        actor: Actor,
        request: BreakdownRequest,
    ) -> BreakdownResult:
        if actor.role is not ActorRole.HUMAN:
            raise AppError(
                403, "human_only", "Only a human may request a PRD breakdown."
            )

        retry_after = self.limiter.hit(f"breakdown:{actor.id}")
        if retry_after is not None:
            seconds = max(1, int(retry_after) + 1)
            raise AppError(
                429,
                "rate_limited",
                "Too many breakdown requests. Try again later.",
                details={
                    "limit": self.settings.breakdown_rate_limit,
                    "window_seconds": self.settings.breakdown_rate_window_seconds,
                },
                headers={"Retry-After": str(seconds)},
            )

        prd = get_prd_or_404(self.store, prd_id)
        prompt_key = request.prompt_version or self.settings.default_prompt_version
        try:
            prompt = get_prompt(prompt_key)
        except KeyError as exc:
            raise AppError(
                422,
                "unknown_prompt_version",
                str(exc),
                details={"available": ["v1", "v2"]},
            ) from exc
        models = self.registry.ordered(request.model)

        warnings: list[str] = []
        injection_labels = scan_injection(prd.body)
        if injection_labels:
            warnings.append(
                "prompt_injection_detected:" + ",".join(injection_labels)
            )
        safe_body, _ = neutralize(prd.body)

        started = time.perf_counter()
        attempts = 0
        failures: list[str] = []
        winner_name: str | None = None
        winner: object | None = None

        try:
            async with asyncio.timeout(self.settings.breakdown_timeout_seconds):
                for model_name in models:
                    provider = self.registry.get(model_name)
                    for attempt in range(self.settings.model_retries + 1):
                        attempts += 1
                        try:
                            output = await provider.generate(
                                title=prd.title,
                                body=safe_body,
                                system_prompt=prompt.system,
                                prompt_version=prompt.key,
                            )
                            _validate_output(
                                output.breakdown,
                                self.settings.max_cards_per_breakdown,
                            )
                        except (ValidationError, ValueError) as exc:
                            failures.append(f"{model_name}:invalid_output:{attempt + 1}")
                            warnings.append(
                                f"{model_name} attempt {attempt + 1} failed validation"
                            )
                            continue
                        except Exception as exc:  # provider failures are retryable
                            failures.append(
                                f"{model_name}:provider_error:{type(exc).__name__}"
                            )
                            warnings.append(
                                f"{model_name} attempt {attempt + 1} failed "
                                f"({type(exc).__name__})"
                            )
                            continue
                        winner_name = model_name
                        winner = output
                        break
                    if winner is not None:
                        break
        except TimeoutError as exc:
            raise AppError(
                504,
                "provider_timeout",
                "The model call exceeded the breakdown deadline.",
                details={
                    "timeout_seconds": self.settings.breakdown_timeout_seconds,
                    "attempts": attempts,
                },
            ) from exc

        if winner is None or winner_name is None:
            raise AppError(
                502,
                "provider_error",
                "Every model attempt failed. No cards were created.",
                details={
                    "attempts": attempts,
                    "models_tried": models,
                    "failures": failures,
                },
            )

        breakdown: Breakdown = winner.breakdown  # type: ignore[attr-defined]
        created = [
            self.store.create_card(
                title=draft.title,
                goal=draft.goal,
                acceptance_criteria=draft.acceptance_criteria,
                out_of_scope=[],
                created_by=actor.id,
                prd_id=prd.id,
                depends_on=draft.depends_on,
            )
            for draft in breakdown.cards
        ]

        fallback_used = winner_name != models[0]
        if fallback_used:
            warnings.append(f"primary_model_failed_fallback_used:{winner_name}")
        if attempts > (1 if winner_name == models[0] else 0):
            warnings.append(f"model_attempts:{attempts}")
        warnings = list(dict.fromkeys(warnings))

        return BreakdownResult(
            prd_id=prd.id,
            cards=created,
            model_used=winner_name,
            fallback_used=fallback_used,
            prompt_version=prompt.key,
            attempts=attempts,
            usage=Usage(
                input_tokens=winner.input_tokens,  # type: ignore[attr-defined]
                output_tokens=winner.output_tokens,  # type: ignore[attr-defined]
                estimated_cost_usd=estimate_cost(
                    winner_name,
                    winner.input_tokens,  # type: ignore[attr-defined]
                    winner.output_tokens,  # type: ignore[attr-defined]
                ),
            ),
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            warnings=warnings,
        )
