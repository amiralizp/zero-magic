"""Shared fixtures: a fresh app and store per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        breakdown_timeout_seconds=2.0,
        breakdown_rate_limit=100,
        breakdown_rate_window_seconds=60.0,
        max_prd_chars=20_000,
        max_cards_per_breakdown=10,
        model_retries=2,
        primary_model="mock-strong",
        fallback_model="mock-fast",
        frontend_origin="http://localhost:5173",
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings=settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
