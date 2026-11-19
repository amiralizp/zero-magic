"""Alembic migration metadata checks (no database required)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parent.parent


def _script_dir() -> ScriptDirectory:
    cfg = Config(str(ROOT / "alembic.ini"))
    # The URL comes from the environment, not the ini file.
    return ScriptDirectory.from_config(cfg)


def test_two_revisions_in_order_with_single_head():
    sd = _script_dir()
    revisions = list(sd.walk_revisions())
    assert len(revisions) == 2
    heads = sd.get_heads()
    assert len(heads) == 1


def test_revision_chain():
    sd = _script_dir()
    revs = {r.revision: r for r in sd.walk_revisions()}
    # first revision has no down_revision
    first = [r for r in revs.values() if r.down_revision is None]
    assert len(first) == 1
    first_rev = first[0]
    # second revision points to first
    second = [r for r in revs.values() if r.down_revision == first_rev.revision]
    assert len(second) == 1


def test_no_literal_password_or_url_in_migration_files():
    forbidden = ["postgresql://", "postgresql+psycopg://"]
    files = [
        ROOT / "migrations" / "env.py",
        ROOT / "migrations" / "versions" / "b7abf173e687_initial_schema.py",
        ROOT / "migrations" / "versions" / "d007f827e746_add_users_table.py",
    ]
    for f in files:
        text = f.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{f.name} contains {token}"


def test_alembic_ini_has_empty_sqlalchemy_url():
    text = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("sqlalchemy.url"):
            # must be empty (nothing after =)
            assert line.strip() == "sqlalchemy.url =", (
                f"sqlalchemy.url is not empty: {line!r}"
            )
            break
    else:
        raise AssertionError("sqlalchemy.url not found in alembic.ini")
