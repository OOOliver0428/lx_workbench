"""add ai chat history

Revision ID: d1f2a3b4c5e6
Revises: c8a4d7e2f906
Create Date: 2026-08-14 16:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1f2a3b4c5e6"
down_revision: str | None = "c8a4d7e2f906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "seq", name="uq_ai_chat_messages_user_seq"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_ai_chat_messages_role"
        ),
        sa.CheckConstraint("seq >= 0", name="ck_ai_chat_messages_seq"),
    )
    op.create_index(
        op.f("ix_ai_chat_messages_user_id"),
        "ai_chat_messages",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ai_chat_messages_user_id"),
        table_name="ai_chat_messages",
    )
    op.drop_table("ai_chat_messages")
