"""enforce half-hour work record steps

Revision ID: d8e7f6a5b4c3
Revises: c14d0f38a921
Create Date: 2026-07-27 21:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d8e7f6a5b4c3"
down_revision: Union[str, None] = "c14d0f38a921"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite cannot rebuild a referenced table while foreign keys are enabled.
        # Triggers enforce the stricter rule without replacing work_records.
        op.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_work_records"))
        op.execute(
            sa.text(
                """
                CREATE TRIGGER ck_work_records_minutes_insert
                BEFORE INSERT ON work_records
                FOR EACH ROW
                WHEN NEW.minutes < 30
                  OR NEW.minutes > 1440
                  OR NEW.minutes % 30 != 0
                BEGIN
                    SELECT RAISE(ABORT, 'work record minutes must use half-hour steps');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER ck_work_records_minutes_update
                BEFORE UPDATE OF minutes ON work_records
                FOR EACH ROW
                WHEN NEW.minutes < 30
                  OR NEW.minutes > 1440
                  OR NEW.minutes % 30 != 0
                BEGIN
                    SELECT RAISE(ABORT, 'work record minutes must use half-hour steps');
                END
                """
            )
        )
    else:
        op.drop_constraint(
            "ck_work_records_minutes",
            "work_records",
            type_="check",
        )
        op.create_check_constraint(
            "ck_work_records_minutes",
            "work_records",
            "minutes >= 30 AND minutes <= 1440 AND minutes % 30 = 0",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_work_records_minutes_insert"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_work_records_minutes_update"))
    else:
        op.drop_constraint(
            "ck_work_records_minutes",
            "work_records",
            type_="check",
        )
        op.create_check_constraint(
            "ck_work_records_minutes",
            "work_records",
            "minutes > 0 AND minutes <= 1440",
        )
