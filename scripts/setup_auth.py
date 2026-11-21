"""Create one initial user per seeded actor.

Run this yourself after the migrations, with ``DATABASE_URL`` and
``JWT_SECRET`` set in the environment (or in local .env, never committed).
Usernames are actor ids, roles come from seeded actors, and each created user
gets a random password. Existing users are left untouched. The script prints
only counts and the credentials file path; passwords are written to that file.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from app.actors import SEED_ACTORS
from app.config import Settings
from app.repositories.factory import build_repository
from app.services.auth import bootstrap_users


def main() -> None:
    settings = Settings.from_env()
    if len(settings.jwt_secret) < 32:
        raise SystemExit("JWT_SECRET must be at least 32 characters.")

    passwords = {actor.id: secrets.token_urlsafe(24) for actor in SEED_ACTORS}
    store = build_repository(settings)
    created = bootstrap_users(store, passwords=passwords)

    credentials_path = Path("gantry-credentials.txt")
    lines = ["username\tpassword\trole\tactor_id"]
    for user in created:
        lines.append(
            f"{user.username}\t{passwords[user.actor_id]}\t{user.role.value}\t{user.actor_id}"
        )
    credentials_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"users_created={len(created)}")
    print(f"credentials_file={credentials_path.resolve()}")


if __name__ == "__main__":
    main()
