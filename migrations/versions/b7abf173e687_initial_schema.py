"""initial schema

Revision ID: b7abf173e687
Revises: None
Create Date: 2026-11-19 10:07:13.924031

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7abf173e687'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "actors",
        sa.Column("id", sa.String(80), primary_key=True, nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
    )

    op.create_table(
        "prds",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["actors.id"]),
    )

    op.create_table(
        "cards",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("goal", sa.String(400), nullable=False),
        sa.Column("acceptance_criteria", postgresql.JSONB(), nullable=False),
        sa.Column("out_of_scope", postgresql.JSONB(), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("assignee_id", sa.String(80), nullable=True),
        sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("prd_id", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("built_by", sa.String(80), nullable=True),
        sa.Column("depends_on", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(["assignee_id"], ["actors.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["actors.id"]),
        sa.ForeignKeyConstraint(["built_by"], ["actors.id"]),
        sa.ForeignKeyConstraint(["prd_id"], ["prds.id"]),
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("card_id", sa.String(40), nullable=False),
        sa.Column("author_id", sa.String(80), nullable=False),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["actors.id"]),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("event", sa.String(80), nullable=False),
        sa.Column("subject_id", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
    )

    op.create_index("ix_cards_stage", "cards", ["stage"])
    op.create_index("ix_cards_assignee", "cards", ["assignee_id"])
    op.create_index("ix_comments_card", "comments", ["card_id", "created_at"])
    op.create_index("ix_audit_created", "audit_log", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_created", table_name="audit_log")
    op.drop_index("ix_comments_card", table_name="comments")
    op.drop_index("ix_cards_assignee", table_name="cards")
    op.drop_index("ix_cards_stage", table_name="cards")

    op.drop_table("audit_log")
    op.drop_table("comments")
    op.drop_table("cards")
    op.drop_table("prds")
    op.drop_table("actors")
