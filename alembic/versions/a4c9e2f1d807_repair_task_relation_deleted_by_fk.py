"""repair legacy task relation deleted-by foreign key

Revision ID: a4c9e2f1d807
Revises: f7d3a9c2b104
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c9e2f1d807"
down_revision: str | None = "f7d3a9c2b104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "fk_task_relations_deleted_by_users"


def _deleted_by_foreign_key() -> dict[str, object] | None:
    inspector = sa.inspect(op.get_bind())
    return next(
        (
            foreign_key
            for foreign_key in inspector.get_foreign_keys("task_relations")
            if foreign_key["constrained_columns"] == ["deleted_by"]
        ),
        None,
    )


def upgrade() -> None:
    if _deleted_by_foreign_key() is not None:
        return
    with op.batch_alter_table("task_relations") as batch_op:
        batch_op.create_foreign_key(
            _CONSTRAINT_NAME,
            "users",
            ["deleted_by"],
            ["id"],
        )


def downgrade() -> None:
    foreign_key = _deleted_by_foreign_key()
    if foreign_key is None or foreign_key["name"] != _CONSTRAINT_NAME:
        return
    with op.batch_alter_table("task_relations") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="foreignkey")
