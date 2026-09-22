"""Add changelog same-day sort order."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8a1b2c3d4e5"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("changelog_entries") as batch_op:
        batch_op.add_column(
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_index(
            "ix_changelog_entries_day_sort",
            ["occurred_at", "sort_order"],
        )


def downgrade() -> None:
    with op.batch_alter_table("changelog_entries") as batch_op:
        batch_op.drop_index("ix_changelog_entries_day_sort")
        batch_op.drop_column("sort_order")
