"""enforce team summary idempotency

Revision ID: b3f8d2a6c901
Revises: e5b9c7d1a304
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3f8d2a6c901"
down_revision: str | None = "e5b9c7d1a304"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, generated_by, week_start FROM team_weekly_summaries "
            "ORDER BY generated_by, week_start, created_at DESC, id DESC"
        )
    ).mappings()
    seen: set[tuple[str, str]] = set()
    duplicate_ids: list[str] = []
    for row in rows:
        key = (row["generated_by"], str(row["week_start"]))
        if key in seen:
            duplicate_ids.append(row["id"])
        else:
            seen.add(key)
    for offset in range(0, len(duplicate_ids), 500):
        id_batch = duplicate_ids[offset : offset + 500]
        connection.execute(
            sa.text("DELETE FROM team_weekly_summaries WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": id_batch},
        )
    with op.batch_alter_table("team_weekly_summaries") as batch_op:
        batch_op.create_unique_constraint(
            "uq_team_weekly_summaries_generator_week",
            ["generated_by", "week_start"],
        )


def downgrade() -> None:
    with op.batch_alter_table("team_weekly_summaries") as batch_op:
        batch_op.drop_constraint(
            "uq_team_weekly_summaries_generator_week",
            type_="unique",
        )
