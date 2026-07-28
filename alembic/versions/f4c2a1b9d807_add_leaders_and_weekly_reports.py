"""add direct leaders and weekly reports

Revision ID: f4c2a1b9d807
Revises: d8e7f6a5b4c3
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4c2a1b9d807"
down_revision: str | None = "d8e7f6a5b4c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # Rebuilding users would require dropping a table referenced by almost
        # every business table. SQLite can safely add this nullable self-FK
        # directly, so keep the migration incremental.
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_users")
        op.execute(
            "ALTER TABLE users ADD COLUMN leader_id VARCHAR(36) "
            "REFERENCES users(id) ON DELETE SET NULL"
        )
        op.create_index("ix_users_leader_id", "users", ["leader_id"], unique=False)
    else:
        op.add_column(
            "users",
            sa.Column(
                "leader_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_users_leader_id", "users", ["leader_id"], unique=False)

    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("submitted_content", sa.Text(), nullable=True),
        sa.Column("submitted_to_id", sa.String(length=36), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation_model", sa.String(length=120), nullable=True),
        sa.Column("generation_usage", sa.JSON(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("week_end >= week_start", name="ck_weekly_reports_valid_week"),
        sa.CheckConstraint(
            "submission_version >= 0",
            name="ck_weekly_reports_submission_version",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["submitted_to_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "author_id",
            "week_start",
            name="uq_weekly_reports_author_week",
        ),
    )
    with op.batch_alter_table("weekly_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_weekly_reports_author_id"),
            ["author_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_weekly_reports_submitted_to_id"),
            ["submitted_to_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_weekly_reports_recipient_submitted",
            ["submitted_to_id", "submitted_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("weekly_reports", schema=None) as batch_op:
        batch_op.drop_index("ix_weekly_reports_recipient_submitted")
        batch_op.drop_index(batch_op.f("ix_weekly_reports_submitted_to_id"))
        batch_op.drop_index(batch_op.f("ix_weekly_reports_author_id"))
    op.drop_table("weekly_reports")

    op.drop_index("ix_users_leader_id", table_name="users")
    op.drop_column("users", "leader_id")
