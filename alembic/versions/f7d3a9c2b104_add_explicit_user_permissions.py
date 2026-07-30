"""add explicit user permissions

Revision ID: f7d3a9c2b104
Revises: e2b8c4d6f901
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7d3a9c2b104"
down_revision: str | None = "e2b8c4d6f901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_permissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("permission_key", sa.String(length=80), nullable=False),
        sa.Column("granted_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "permission_key",
            name="uq_user_permissions_user_key",
        ),
    )
    op.create_index(
        op.f("ix_user_permissions_user_id"),
        "user_permissions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_permissions_user_id"),
        table_name="user_permissions",
    )
    op.drop_table("user_permissions")
