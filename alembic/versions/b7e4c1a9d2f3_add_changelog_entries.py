"""add changelog entries

Revision ID: b7e4c1a9d2f3
Revises: a6e1c3f9b204
Create Date: 2026-09-11 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e4c1a9d2f3"
down_revision: str | None = "a6e1c3f9b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "changelog_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN ('feature', 'improvement', 'fix', 'removal')",
            name="ck_changelog_entries_category",
        ),
    )
    op.create_index(
        op.f("ix_changelog_entries_occurred_at"),
        "changelog_entries",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_changelog_entries_category"),
        "changelog_entries",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_changelog_entries_created_by"),
        "changelog_entries",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        "ix_changelog_entries_occurred",
        "changelog_entries",
        ["occurred_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_changelog_entries_occurred", table_name="changelog_entries"
    )
    op.drop_index(
        op.f("ix_changelog_entries_created_by"), table_name="changelog_entries"
    )
    op.drop_index(
        op.f("ix_changelog_entries_category"), table_name="changelog_entries"
    )
    op.drop_index(
        op.f("ix_changelog_entries_occurred_at"), table_name="changelog_entries"
    )
    op.drop_table("changelog_entries")
