"""add war-room dashboard facts

Revision ID: e2b8c4d6f901
Revises: a1c7e3f9b2d4
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2b8c4d6f901"
down_revision: str | None = "a1c7e3f9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_progress",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("business_stage", sa.String(length=32), nullable=False),
        sa.Column("attention_status", sa.String(length=32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_project_progress_percent",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_project_progress_project_id"),
        "project_progress",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_progress_week_start"),
        "project_progress",
        ["week_start"],
        unique=False,
    )
    op.create_index(
        "ix_project_progress_project_week_created",
        "project_progress",
        ["project_id", "week_start", "created_at"],
        unique=False,
    )

    op.create_table(
        "task_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_task_id", sa.String(length=36), nullable=False),
        sa.Column("target_task_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "source_task_id <> target_task_id",
            name="ck_task_relations_distinct_tasks",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id"],
            ["tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_task_id"],
            ["tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_task_id",
            "target_task_id",
            name="uq_task_relations_pair",
        ),
    )
    op.create_index(
        op.f("ix_task_relations_source_task_id"),
        "task_relations",
        ["source_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_relations_target_task_id"),
        "task_relations",
        ["target_task_id"],
        unique=False,
    )

    op.create_table(
        "team_weekly_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=36), nullable=False),
        sa.Column("forced", sa.Boolean(), nullable=False),
        sa.Column("submitted_count", sa.Integer(), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("generation_model", sa.String(length=120), nullable=False),
        sa.Column("generation_usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "week_end >= week_start",
            name="ck_team_weekly_summaries_valid_week",
        ),
        sa.CheckConstraint(
            "submitted_count >= 0 AND expected_count >= submitted_count",
            name="ck_team_weekly_summaries_counts",
        ),
        sa.ForeignKeyConstraint(
            ["generated_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_team_weekly_summaries_week_start"),
        "team_weekly_summaries",
        ["week_start"],
        unique=False,
    )
    op.create_index(
        "ix_team_weekly_summaries_week_created",
        "team_weekly_summaries",
        ["week_start", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_team_weekly_summaries_week_created",
        table_name="team_weekly_summaries",
    )
    op.drop_index(
        op.f("ix_team_weekly_summaries_week_start"),
        table_name="team_weekly_summaries",
    )
    op.drop_table("team_weekly_summaries")

    op.drop_index(
        op.f("ix_task_relations_target_task_id"),
        table_name="task_relations",
    )
    op.drop_index(
        op.f("ix_task_relations_source_task_id"),
        table_name="task_relations",
    )
    op.drop_table("task_relations")

    op.drop_index(
        "ix_project_progress_project_week_created",
        table_name="project_progress",
    )
    op.drop_index(
        op.f("ix_project_progress_week_start"),
        table_name="project_progress",
    )
    op.drop_index(
        op.f("ix_project_progress_project_id"),
        table_name="project_progress",
    )
    op.drop_table("project_progress")
