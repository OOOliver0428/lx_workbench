"""Preserve weekly membership and distinguish unknown legacy departments."""

import sqlalchemy as sa

from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "weekly_rosters",
        sa.Column("week_start", sa.Date(), primary_key=True),
        sa.Column("members", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("weekly_reports") as batch:
        batch.add_column(
            sa.Column("department_snapshot_known", sa.Boolean(), nullable=False, server_default="0")
        )
    op.execute(
        "UPDATE weekly_reports SET department_snapshot_known = 1 WHERE department_id IS NOT NULL"
    )
    with op.batch_alter_table("team_weekly_summaries") as batch:
        batch.add_column(
            sa.Column("expected_count_known", sa.Boolean(), nullable=False, server_default="1")
        )
    # Old all_led rows may include reporting-tree members outside led departments.
    # Keep them accessible as historical summaries, never as a current scope result.
    op.execute(
        "UPDATE team_weekly_summaries SET scope_type = 'legacy', "
        "scope_key = 'legacy' WHERE scope_key = 'all_led'"
    )


def downgrade():
    with op.batch_alter_table("team_weekly_summaries") as batch:
        batch.drop_column("expected_count_known")
    with op.batch_alter_table("weekly_reports") as batch:
        batch.drop_column("department_snapshot_known")
    op.drop_table("weekly_rosters")
