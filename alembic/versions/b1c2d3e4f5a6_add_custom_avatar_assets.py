"""Add private custom avatar resources (v0.5.1)."""

import sqlalchemy as sa

from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False, unique=True),
        sa.Column("version_id", sa.String(256)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("cleanup_after", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'active', 'retired', 'deleting')",
            name="ck_avatar_assets_state",
        ),
    )
    op.create_index("ix_avatar_assets_user_created", "avatar_assets", ["user_id", "created_at"])
    op.create_index("ix_avatar_assets_cleanup_after", "avatar_assets", ["cleanup_after"])


def downgrade() -> None:
    # Older code cannot render custom keys; retain each user's other profile data.
    op.execute("UPDATE users SET avatar_key = NULL WHERE avatar_key LIKE 'custom-%'")
    op.drop_table("avatar_assets")
