"""add AI provider access mode

Revision ID: c14d0f38a921
Revises: b6a3d9c1e4f2
Create Date: 2026-07-27 20:15:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c14d0f38a921"
down_revision: Union[str, None] = "b6a3d9c1e4f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_provider_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "access_mode",
                sa.String(length=32),
                nullable=False,
                server_default="standard",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_provider_configs") as batch_op:
        batch_op.drop_column("access_mode")
