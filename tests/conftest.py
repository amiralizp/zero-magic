"""Shared fixtures: a fresh app, token client and store per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.helpers import (
    TEST_JWT_SECRET,
    TEST_TOKEN_TTL_SECONDS,
    AuthenticatedTestClient,
    seed_test_users,
)


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
        jwt_secret=TEST_JWT_SECRET,
        token_ttl_seconds=TEST_TOKEN_TTL_SECONDS,
    )


@pytest.fixture
def app(settings: Settings):
    application = create_app(settings=settings)
    seed_test_users(application.state.store)
    return application


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with AuthenticatedTestClient(app) as test_client:
        yield test_client
