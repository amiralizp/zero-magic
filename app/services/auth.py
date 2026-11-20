"""Authentication rules: password hashing and signed-token identity.

This module is framework-free (ADR 0007). It imports the Argon2 and JWT
libraries directly, reads no HTTP request and returns no HTTP response. The
HTTP layer only turns a token into a caller; this module owns how tokens are
made, checked and rejected.

The installed ``argon2-cffi`` docs recommend one ``PasswordHasher`` instance
so parameters are validated once; its default is Argon2id with the RFC 9106
low-memory profile. The installed ``PyJWT`` docs require an explicit algorithm
list on decode, so HS256 is hard-coded here and never taken from the token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..actors import AGENT_BUILDER, HUMAN_ADA
from ..domain_errors import AppError
from ..records import UserRecord
from ..repositories.factory import Repository
from ..schemas.actors import ActorRole

ALGORITHM = "HS256"
ISSUER = "gantry"
MIN_SECRET_LENGTH = 32

_hasher = PasswordHasher()


@dataclass(frozen=True)
class TokenIdentity:
    """The caller a signed token claims to be."""

    actor_id: str
    username: str
    role: ActorRole


def _require_secret(secret: str) -> None:
    if len(secret) < MIN_SECRET_LENGTH:
        raise AppError(
            status_code=500,
            code="auth_misconfigured",
            message=f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters.",
        )


def hash_password(password: str) -> str:
    """Return an encoded Argon2 hash; the plaintext is never stored."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against a stored hash without leaking why it failed."""
    try:
        return bool(_hasher.verify(password_hash, password))
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def issue_token(
    *,
    actor_id: str,
    username: str,
    role: ActorRole,
    secret: str,
    ttl_seconds: int,
) -> str:
    """Sign a short-lived token whose subject is an actor id."""
    _require_secret(secret)
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "sub": actor_id,
        "username": username,
        "role": role.value,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> TokenIdentity:
    """Verify signature, issuer and expiry, then return the claimed identity."""
    _require_secret(secret)
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "sub", "username", "role"]},
        )
    except jwt.PyJWTError as exc:
        raise AppError(
            status_code=401,
            code="invalid_token",
            message="The token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    actor_id = claims.get("sub")
    username = claims.get("username")
    role_value = claims.get("role")
    if (
        not isinstance(actor_id, str)
        or not actor_id
        or not isinstance(username, str)
        or not username
        or not isinstance(role_value, str)
    ):
        raise AppError(
            status_code=401,
            code="invalid_token",
            message="The token is missing identity claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        role = ActorRole(role_value)
    except ValueError as exc:
        raise AppError(
            status_code=401,
            code="invalid_token",
            message="The token has an unknown role.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return TokenIdentity(actor_id=actor_id, username=username, role=role)


def authenticate(
    store: Repository,
    username: str,
    password: str,
    *,
    secret: str,
    ttl_seconds: int,
) -> str:
    """Return a signed token for valid credentials, else a generic 401."""
    _require_secret(secret)
    user = store.get_user_by_username(username)
    if user is None or not verify_password(user.password_hash, password):
        raise AppError(
            status_code=401,
            code="invalid_credentials",
            message="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return issue_token(
        actor_id=user.actor_id,
        username=user.username,
        role=user.role,
        secret=secret,
        ttl_seconds=ttl_seconds,
    )


def bootstrap_users(
    store: Repository,
    *,
    human_password: str,
    agent_password: str,
) -> list[UserRecord]:
    """Create the two initial users if they are absent.

    Passwords come from the caller (environment in production, test fixtures in
    the suite). Nothing here contains a real credential. Existing users are
    left untouched so a restart never overwrites a rotated password.
    """
    specs = (
        ("ada", HUMAN_ADA, ActorRole.HUMAN, human_password),
        ("builder", AGENT_BUILDER, ActorRole.AGENT, agent_password),
    )
    created: list[UserRecord] = []
    for username, actor_id, role, password in specs:
        if not password:
            continue
        if store.get_user_by_username(username) is not None:
            continue
        created.append(
            store.create_user(
                username=username,
                password_hash=hash_password(password),
                role=role,
                actor_id=actor_id,
            )
        )
    return created
