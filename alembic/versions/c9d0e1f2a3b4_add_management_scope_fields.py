"""add management scope to team summaries and weekly report department snapshot

Revision ID: c9d0e1f2a3b4
Revises: b7e4c1a9d2f3
Create Date: 2026-09-11 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b7e4c1a9d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("weekly_reports") as batch_op:
        batch_op.add_column(
            sa.Column("department_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_weekly_reports_department_id_departments",
            "departments",
            ["department_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_weekly_reports_department_id",
            ["department_id"],
            unique=False,
        )

    with op.batch_alter_table("team_weekly_summaries") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scope_type",
                sa.String(length=32),
                nullable=False,
                server_default="all_led",
            )
        )
        batch_op.add_column(
            sa.Column("department_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "scope_key",
                sa.String(length=80),
                nullable=False,
                server_default="all_led",
            )
        )
        batch_op.drop_constraint(
            "uq_team_weekly_summaries_generator_week", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_team_weekly_summaries_generator_week_scope",
            ["generated_by", "week_start", "scope_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("team_weekly_summaries") as batch_op:
        batch_op.drop_constraint(
            "uq_team_weekly_summaries_generator_week_scope", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_team_weekly_summaries_generator_week",
            ["generated_by", "week_start"],
        )
        batch_op.drop_column("scope_key")
        batch_op.drop_column("department_id")
        batch_op.drop_column("scope_type")

    with op.batch_alter_table("weekly_reports") as batch_op:
        batch_op.drop_index("ix_weekly_reports_department_id")
        batch_op.drop_constraint(
            "fk_weekly_reports_department_id_departments", type_="foreignkey"
        )
        batch_op.drop_column("department_id")
