"""add work record time blocks

Revision ID: f1a6b7c8d902
Revises: c8a4d7e2f906
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a6b7c8d902"
down_revision: str | None = "c8a4d7e2f906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_record_time_blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND end_minute > start_minute",
            name="ck_wrtb_range",
        ),
        sa.CheckConstraint(
            "start_minute % 30 = 0 AND end_minute % 30 = 0",
            name="ck_wrtb_slot",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["work_records.id"],
            name="fk_wrtb_record_id_work_records",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wrtb_record",
        "work_record_time_blocks",
        ["record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_wrtb_record", table_name="work_record_time_blocks")
    op.drop_table("work_record_time_blocks")
