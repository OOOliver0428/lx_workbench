"""Allow version release markers in the changelog.

Revision ID: d2e3f4a5b6c7
Revises: c9d0e1f2a3b4
"""

from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("changelog_entries") as batch_op:
        batch_op.drop_constraint("ck_changelog_entries_category", type_="check")
        batch_op.create_check_constraint(
            "ck_changelog_entries_category",
            "category IN ('feature', 'improvement', 'fix', 'removal', 'release')",
        )


def downgrade() -> None:
    # Preserve release markers as ordinary entries that older clients can display.
    op.execute(
        "UPDATE changelog_entries SET category = 'improvement', "
        "body = '版本更新：' || title WHERE category = 'release'"
    )
    with op.batch_alter_table("changelog_entries") as batch_op:
        batch_op.drop_constraint("ck_changelog_entries_category", type_="check")
        batch_op.create_check_constraint(
            "ck_changelog_entries_category",
            "category IN ('feature', 'improvement', 'fix', 'removal')",
        )
