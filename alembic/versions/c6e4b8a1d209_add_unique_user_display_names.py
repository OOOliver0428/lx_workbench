"""add unique normalized user display names

Revision ID: c6e4b8a1d209
Revises: a4c9e2f1d807
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c6e4b8a1d209"
down_revision: str | None = "a4c9e2f1d807"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "uq_users_display_name_key"


def _normalize(value: str) -> str:
    return value.strip().casefold()


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("display_name_key", sa.String(length=512), nullable=True),
    )

    connection = op.get_bind()
    users = connection.execute(
        sa.text("SELECT id, login_name, display_name FROM users")
    ).mappings()
    rows = list(users)
    login_owners = {_normalize(row["login_name"]): row["id"] for row in rows}
    display_owners: dict[str, str] = {}

    for row in rows:
        display_name = row["display_name"].strip()
        display_name_key = _normalize(display_name)
        if not display_name_key:
            raise RuntimeError("用户显示名称不能为空，无法执行迁移")
        existing_owner = display_owners.get(display_name_key)
        if existing_owner and existing_owner != row["id"]:
            raise RuntimeError("存在重复的用户显示名称，请先修复后再执行迁移")
        login_owner = login_owners.get(display_name_key)
        if login_owner and login_owner != row["id"]:
            raise RuntimeError("用户显示名称与其他账号的登录名冲突，请先修复后再执行迁移")
        display_owners[display_name_key] = row["id"]
        connection.execute(
            sa.text(
                """
                UPDATE users
                SET display_name = :display_name,
                    display_name_key = :display_name_key
                WHERE id = :user_id
                """
            ),
            {
                "display_name": display_name,
                "display_name_key": display_name_key,
                "user_id": row["id"],
            },
        )

    op.create_index(
        _INDEX_NAME,
        "users",
        ["display_name_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="users")
    op.drop_column("users", "display_name_key")
