"""add user avatar key

Revision ID: a1c7e3f9b2d4
Revises: f4c2a1b9d807
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c7e3f9b2d4"
down_revision: str | None = "f4c2a1b9d807"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_key", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_key")
