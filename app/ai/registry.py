"""Provider registry and configuration.

The registry owns the model order (primary, then fallback). The service asks it
for an ordered list so fallback policy is testable without touching HTTP.
"""

from __future__ import annotations

from ..config import Settings
from ..domain_errors import AppError
from .providers.base import BreakdownProvider
from .providers.mock import make_mock_providers
from .providers.openrouter import OpenRouterProvider


def build_providers(settings: Settings) -> dict[str, BreakdownProvider]:
    providers: dict[str, BreakdownProvider] = dict(make_mock_providers())
    if settings.openrouter_api_key:
        for name in (settings.primary_model, settings.fallback_model):
            if name not in providers:
                providers[name] = OpenRouterProvider(
                    name=name,
                    api_key=settings.openrouter_api_key,
                    base_url=settings.openrouter_base_url,
                    timeout_seconds=settings.breakdown_timeout_seconds,
                )
    for name in (settings.primary_model, settings.fallback_model):
        if name not in providers:
            raise RuntimeError(
                f"Model {name!r} is not available. Set OPENROUTER_API_KEY to use "
                "a real model, or use mock-strong / mock-fast."
            )
    return providers


class ProviderRegistry:
    def __init__(
        self,
        providers: dict[str, BreakdownProvider],
        *,
        primary: str,
        fallback: str,
    ) -> None:
        self._providers = providers
        self.primary = primary
        self.fallback = fallback

    @property
    def names(self) -> list[str]:
        return sorted(self._providers)

    def get(self, name: str) -> BreakdownProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise RuntimeError(f"Unknown provider {name!r}") from exc

    def ordered(self, requested: str | None = None) -> list[str]:
        if requested is not None:
            if requested not in self._providers:
                raise AppError(
                    422,
                    "unknown_model",
                    f"Model {requested!r} is not configured.",
                    details={"available": self.names},
                )
            return [requested]

        names: list[str] = []
        for name in (self.primary, self.fallback):
            if name not in names:
                names.append(name)
        return names
