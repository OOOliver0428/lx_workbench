"""split opportunity, project, and task permissions

Revision ID: e5b9c7d1a304
Revises: d2c7f4a9e601
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5b9c7d1a304"
down_revision: str | None = "d2c7f4a9e601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    permissions = sa.table(
        "user_permissions",
        sa.column("permission_key", sa.String()),
    )
    op.execute(
        permissions.update()
        .where(permissions.c.permission_key == "projects.manage")
        .values(permission_key="projects.create")
    )
    op.execute(
        permissions.update()
        .where(permissions.c.permission_key == "tasks.manage")
        .values(permission_key="tasks.create")
    )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, user_id, permission_key FROM user_permissions "
            "WHERE permission_key IN "
            "('projects.edit', 'projects.create', 'tasks.edit', 'tasks.create')"
        )
    ).mappings()
    user_permissions: dict[tuple[str, str], str] = {}
    delete_ids: list[str] = []
    for row in rows:
        legacy_key = (
            "projects.manage"
            if row["permission_key"].startswith("projects.")
            else "tasks.manage"
        )
        identity = (row["user_id"], legacy_key)
        if identity in user_permissions:
            delete_ids.append(row["id"])
            continue
        user_permissions[identity] = row["id"]
        connection.execute(
            sa.text(
                "UPDATE user_permissions SET permission_key = :permission_key "
                "WHERE id = :id"
            ),
            {"id": row["id"], "permission_key": legacy_key},
        )
    if delete_ids:
        connection.execute(
            sa.text("DELETE FROM user_permissions WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": delete_ids},
        )

