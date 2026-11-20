"""Create the two initial users from environment values.

Run this yourself after the migrations, with ``DATABASE_URL``, ``JWT_SECRET``,
``GANTRY_HUMAN_PASSWORD`` and ``GANTRY_AGENT_PASSWORD`` set in the environment
(or in the local .env, which is never committed). It prints usernames only;
passwords and hashes are never printed. Existing users are not overwritten.
"""

from __future__ import annotations

import os

from app.config import Settings
from app.repositories.factory import build_repository
from app.services.auth import bootstrap_users


def main() -> None:
    settings = Settings.from_env()
    human_password = os.getenv("GANTRY_HUMAN_PASSWORD", "")
    agent_password = os.getenv("GANTRY_AGENT_PASSWORD", "")
    if not human_password or not agent_password:
        raise SystemExit(
            "Set GANTRY_HUMAN_PASSWORD and GANTRY_AGENT_PASSWORD before running setup_auth."
        )
    if len(settings.jwt_secret) < 32:
        raise SystemExit("JWT_SECRET must be at least 32 characters.")

    store = build_repository(settings)
    users = bootstrap_users(
        store,
        human_password=human_password,
        agent_password=agent_password,
    )
    for user in users:
        print(f"created user {user.username} ({user.role.value}) -> {user.actor_id}")
    if not users:
        print("both initial users already exist; nothing changed")


if __name__ == "__main__":
    main()
