"""add users table

Revision ID: d007f827e746
Revises: b7abf173e687
Create Date: 2026-11-19 10:07:18.194237

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd007f827e746'
down_revision: Union[str, Sequence[str], None] = 'b7abf173e687'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.id"]),
        sa.CheckConstraint("role IN ('human', 'agent')", name="ck_users_role"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("users")
