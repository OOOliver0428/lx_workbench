"""Add optional encrypted phone verification (v0.5.1)."""

import sqlalchemy as sa

from alembic import op

revision = "a9b8c7d6e5f4"
down_revision = "f8a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite ADD COLUMN avoids rebuilding users and its many dependent foreign keys.
    op.add_column("users", sa.Column("phone_ciphertext", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("phone_key_id", sa.String(40), nullable=True))
    op.add_column("users", sa.Column("phone_lookup_hash", sa.String(64), nullable=True))
    op.add_column(
        "users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("uq_users_phone_lookup_hash", "users", ["phone_lookup_hash"], unique=True)
    op.create_table(
        "phone_crypto_key_checks",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("check_value", sa.String(64), nullable=False),
    )
    op.create_table(
        "phone_challenges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("phone_ciphertext", sa.Text(), nullable=False),
        sa.Column("phone_key_id", sa.String(40), nullable=False),
        sa.Column("phone_lookup_hash", sa.String(64), nullable=False),
        sa.Column("original_phone_hash", sa.String(64)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_until", sa.DateTime(timezone=True), nullable=False),
    )
    for suffix, columns in (
        ("user_created", ["user_id", "created_at"]),
        ("hash_created", ["phone_lookup_hash", "created_at"]),
        ("created", ["created_at"]),
    ):
        op.create_index("ix_phone_challenges_" + suffix, "phone_challenges", columns)


def downgrade() -> None:
    op.drop_table("phone_challenges")
    op.drop_table("phone_crypto_key_checks")
    op.drop_index("uq_users_phone_lookup_hash", table_name="users")
    # Native DROP COLUMN (SQLite >= 3.35) keeps referenced user rows intact.
    for name in ("phone_verified_at", "phone_lookup_hash", "phone_key_id", "phone_ciphertext"):
        op.drop_column("users", name)
