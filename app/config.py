"""Application settings.

Everything is read once, from environment variables, when the app is created.
Tests build their own Settings so limits can be tightened without patching
module globals.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"
DEFAULT_TIMEOUT = 15.0
DEFAULT_RATE_LIMIT = 5
DEFAULT_RATE_WINDOW = 60.0
DEFAULT_MAX_PRD_CHARS = 20_000
DEFAULT_MAX_CARDS = 10
DEFAULT_RETRIES = 2
DEFAULT_PROMPT = "v2"
DEFAULT_PRIMARY_MODEL = "mock-strong"
DEFAULT_FALLBACK_MODEL = "mock-fast"
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    app_name: str = "Gantry API"
    api_version: str = "0.3.0"
    environment: str = "local"

    frontend_origin: str = DEFAULT_FRONTEND_ORIGIN

    breakdown_timeout_seconds: float = DEFAULT_TIMEOUT
    breakdown_rate_limit: int = DEFAULT_RATE_LIMIT
    breakdown_rate_window_seconds: float = DEFAULT_RATE_WINDOW
    max_prd_chars: int = DEFAULT_MAX_PRD_CHARS
    max_cards_per_breakdown: int = DEFAULT_MAX_CARDS
    model_retries: int = DEFAULT_RETRIES
    default_prompt_version: str = DEFAULT_PROMPT

    primary_model: str = DEFAULT_PRIMARY_MODEL
    fallback_model: str = DEFAULT_FALLBACK_MODEL

    openrouter_api_key: str | None = field(default=None, repr=False)
    openrouter_base_url: str = DEFAULT_OPENROUTER_BASE

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.getenv("OPENROUTER_API_KEY") or None
        return cls(
            environment=os.getenv("APP_ENV", "local"),
            frontend_origin=os.getenv("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN),
            breakdown_timeout_seconds=_float("BREAKDOWN_TIMEOUT_SECONDS", DEFAULT_TIMEOUT),
            breakdown_rate_limit=_int("BREAKDOWN_RATE_LIMIT", DEFAULT_RATE_LIMIT),
            breakdown_rate_window_seconds=_float(
                "BREAKDOWN_RATE_WINDOW_SECONDS", DEFAULT_RATE_WINDOW
            ),
            max_prd_chars=_int("MAX_PRD_CHARS", DEFAULT_MAX_PRD_CHARS),
            max_cards_per_breakdown=_int("MAX_CARDS_PER_BREAKDOWN", DEFAULT_MAX_CARDS),
            model_retries=_int("MODEL_RETRIES", DEFAULT_RETRIES),
            default_prompt_version=os.getenv("DEFAULT_PROMPT_VERSION", DEFAULT_PROMPT),
            primary_model=os.getenv("MODEL_PRIMARY", DEFAULT_PRIMARY_MODEL),
            fallback_model=os.getenv("MODEL_FALLBACK", DEFAULT_FALLBACK_MODEL),
            openrouter_api_key=key,
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE),
        )
