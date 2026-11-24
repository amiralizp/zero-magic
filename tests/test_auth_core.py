"""S12 core: hashing, signed tokens and the initial-user bootstrap.

These tests exercise the framework-free service directly. HTTP behaviour is
covered in ``tests/test_auth.py``.
"""

from __future__ import annotations

import pytest

from app.domain_errors import AppError
from app.repositories.memory import InMemoryRepository
from app.schemas.actors import ActorRole
from app.services.auth import (
    bootstrap_users,
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)

from tests.helpers import (
    AGENT,
    HUMAN,
    TEST_AGENT_PASSWORD,
    TEST_HUMAN_PASSWORD,
    TEST_JWT_SECRET,
)


def test_password_hash_is_salted_and_verifies_only_the_original():
    first = hash_password(TEST_HUMAN_PASSWORD)
    second = hash_password(TEST_HUMAN_PASSWORD)

    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password(first, TEST_HUMAN_PASSWORD) is True
    assert verify_password(first, TEST_AGENT_PASSWORD) is False
    assert verify_password("not-an-encoded-hash", TEST_HUMAN_PASSWORD) is False


def test_token_roundtrip_keeps_the_signed_identity():
    token = issue_token(
        actor_id=HUMAN,
        username="ada",
        role=ActorRole.HUMAN,
        secret=TEST_JWT_SECRET,
        ttl_seconds=3600,
    )
    identity = decode_token(token, TEST_JWT_SECRET)

    assert identity.actor_id == HUMAN
    assert identity.username == "ada"
    assert identity.role is ActorRole.HUMAN


def test_token_signature_and_expiry_are_checked():
    token = issue_token(
        actor_id=HUMAN,
        username="ada",
        role=ActorRole.HUMAN,
        secret=TEST_JWT_SECRET,
        ttl_seconds=-60,
    )
    with pytest.raises(AppError) as expired:
        decode_token(token, TEST_JWT_SECRET)
    assert expired.value.code == "invalid_token"

    with pytest.raises(AppError) as wrong_key:
        decode_token(token, "a-different-secret-with-at-least-32-chars")
    assert wrong_key.value.code == "invalid_token"


def test_short_secret_is_a_configuration_error():
    with pytest.raises(AppError) as error:
        issue_token(
            actor_id=HUMAN,
            username="ada",
            role=ActorRole.HUMAN,
            secret="too-short",
            ttl_seconds=3600,
        )
    assert error.value.code == "auth_misconfigured"
    assert error.value.status_code == 500


@pytest.mark.parametrize(
    "secret",
    [
        "replace-with-at-least-32-random-characters",
        "replace-with-something-else-that-is-long-enough",
        "CHANGE_ME_TO_A_REAL_SECRET_THAT_IS_LONG_ENOUGH",
        "changeme-but-make-it-long-enough-to-pass-length",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ],
)
def test_weak_or_placeholder_jwt_secret_is_rejected(secret):
    from app.services.auth import JWT_SECRET_PLACEHOLDER

    candidates = list(dict.fromkeys([*["replace-with-at-least-32-random-characters" if s == "replace-with-at-least-32-random-characters" else s for s in [secret]], JWT_SECRET_PLACEHOLDER]))
    # Test the parametrized secret; also ensure placeholder constant is rejected.
    for candidate in dict.fromkeys([secret, JWT_SECRET_PLACEHOLDER]):
        with pytest.raises(AppError) as error:
            issue_token(
                actor_id=HUMAN,
                username="ada",
                role=ActorRole.HUMAN,
                secret=candidate,
                ttl_seconds=3600,
            )
        assert error.value.code == "auth_misconfigured"
        assert error.value.status_code == 500


def test_strong_generated_jwt_secret_is_accepted():
    import secrets

    token = issue_token(
        actor_id=HUMAN,
        username="ada",
        role=ActorRole.HUMAN,
        secret=secrets.token_urlsafe(48),
        ttl_seconds=3600,
    )
    assert token


def test_authenticate_unknown_user_runs_dummy_verify(monkeypatch):
    from app.repositories.memory import InMemoryRepository
    from app.services import auth

    store = InMemoryRepository()
    called = {"value": False}

    def fake_dummy(password: str) -> bool:
        called["value"] = True
        return False

    monkeypatch.setattr(auth, "_dummy_verify_password", fake_dummy)
    with pytest.raises(AppError) as error:
        auth.authenticate(
            store,
            "nobody",
            "wrong-password",
            secret=TEST_JWT_SECRET,
            ttl_seconds=3600,
        )
    assert error.value.code == "invalid_credentials"
    assert called["value"] is True


def test_bootstrap_creates_all_seed_users_once_without_storing_passwords():
    store = InMemoryRepository()
    created = bootstrap_users(
        store,
        human_password=TEST_HUMAN_PASSWORD,
        agent_password=TEST_AGENT_PASSWORD,
    )
    assert len(created) == 6
    assert {user.username for user in created} == {
        "human:ada",
        "human:grace",
        "human:linus",
        "agent:builder",
        "agent:reviewer",
        "agent:planner",
    }
    ada = next(user for user in created if user.actor_id == HUMAN)
    builder = next(user for user in created if user.actor_id == AGENT)
    assert ada.role is ActorRole.HUMAN
    assert builder.role is ActorRole.AGENT

    again = bootstrap_users(
        store,
        human_password="a-different-password",
        agent_password="a-different-password",
    )
    assert again == []

    ada = store.get_user_by_username("human:ada")
    assert ada is not None
    assert ada.password_hash != TEST_HUMAN_PASSWORD
    assert verify_password(ada.password_hash, TEST_HUMAN_PASSWORD) is True
    assert verify_password(ada.password_hash, "a-different-password") is False
