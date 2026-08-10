"""add department work and task workflow foundations

Revision ID: c8a4d7e2f906
Revises: b3f8d2a6c901
Create Date: 2026-08-10
"""

from collections.abc import Callable, Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8a4d7e2f906"
down_revision: str | None = "b3f8d2a6c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MINUTES_INSERT_TRIGGER = """
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

_MINUTES_UPDATE_TRIGGER = """
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


def _assert_sqlite_foreign_keys_clean(stage: str) -> None:
    violations = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        preview = "; ".join(str(tuple(row)) for row in violations[:10])
        raise RuntimeError(f"foreign key violations {stage}: {preview}")


def _run_sqlite_schema_transaction(callback: Callable[[], None]) -> None:
    """Run referenced-table rebuilds atomically while SQLite FK checks are paused.

    SQLite cannot drop a table that is still referenced while ``foreign_keys`` is
    enabled.  An Alembic autocommit block lets us change that connection setting;
    an explicit SQLite transaction still keeps all schema and copy operations
    atomic.  Constraints are checked against the rebuilt graph before commit.
    """

    _assert_sqlite_foreign_keys_clean("before migration")
    context = op.get_context()
    with context.autocommit_block():
        connection = op.get_bind()
        raw_connection = connection.connection.driver_connection
        cursor = raw_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=OFF")
            if cursor.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
                raise RuntimeError("could not disable SQLite foreign key enforcement")
            cursor.execute("BEGIN IMMEDIATE")
            callback()
            violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                preview = "; ".join(str(tuple(row)) for row in violations[:10])
                raise RuntimeError(f"foreign key violations after migration: {preview}")
            raw_connection.commit()
        except Exception:
            raw_connection.rollback()
            raise
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")
            enabled = cursor.execute("PRAGMA foreign_keys").fetchone()[0]
            cursor.close()
            if enabled != 1:
                raise RuntimeError("could not restore SQLite foreign key enforcement")


def _create_departments() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("leader_id", sa.String(length=36), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["leader_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_departments_leader_id", "departments", ["leader_id"])
    op.create_index(
        "uq_departments_normalized_name_active",
        "departments",
        ["normalized_name"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_departments_active_deleted",
        "departments",
        ["is_active", "deleted_at"],
    )


def _add_user_department() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # Rebuild inside the FK-disabled schema transaction so both references
        # are table-level constraints. SQLAlchemy cannot recover ON DELETE from
        # SQLite's inline REFERENCES syntax, which would otherwise leave every
        # later ``alembic check`` reporting a false schema difference.
        naming_convention = {
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
        }
        with op.batch_alter_table(
            "users",
            recreate="always",
            naming_convention=naming_convention,
        ) as batch_op:
            batch_op.add_column(
                sa.Column("primary_department_id", sa.String(length=36), nullable=True)
            )
            batch_op.drop_constraint(
                "fk_users_leader_id_users",
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                "fk_users_leader_id_users",
                "users",
                ["leader_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_users_primary_department_id_departments",
                "departments",
                ["primary_department_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.add_column(
            "users",
            sa.Column("primary_department_id", sa.String(length=36), nullable=True),
        )
        op.create_foreign_key(
            "fk_users_primary_department_id_departments",
            "users",
            "departments",
            ["primary_department_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_users_primary_department_id",
        "users",
        ["primary_department_id"],
    )


def _create_department_works() -> None:
    op.create_table(
        "department_works",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("department_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_department_works_code"),
    )
    op.create_index(
        "ix_department_works_department_id",
        "department_works",
        ["department_id"],
    )
    op.create_index("ix_department_works_owner_id", "department_works", ["owner_id"])
    op.create_index(
        "uq_department_works_department_name_active",
        "department_works",
        ["department_id", "normalized_name"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL AND status != 'archived'"),
    )
    op.create_index(
        "ix_department_works_department_status_deleted",
        "department_works",
        ["department_id", "status", "deleted_at"],
    )


def _rebuild_tasks() -> None:
    op.add_column(
        "tasks",
        sa.Column("department_work_id", sa.String(length=36), nullable=True),
    )
    op.add_column("tasks", sa.Column("parent_id", sa.String(length=36), nullable=True))
    op.add_column("tasks", sa.Column("level", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("progress_enabled", sa.Boolean(), nullable=True))
    op.add_column("tasks", sa.Column("progress_percent", sa.Integer(), nullable=True))
    task_defaults = sa.table(
        "tasks",
        sa.column("level", sa.Integer()),
        sa.column("progress_enabled", sa.Boolean()),
    )
    op.execute(task_defaults.update().values(level=0, progress_enabled=False))

    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.alter_column(
            "project_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.alter_column(
            "level",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "progress_enabled",
            existing_type=sa.Boolean(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_tasks_department_work_id_department_works",
            "department_works",
            ["department_work_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_tasks_parent_id_tasks",
            "tasks",
            ["parent_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_tasks_exactly_one_source",
            "(project_id IS NOT NULL AND department_work_id IS NULL) OR "
            "(project_id IS NULL AND department_work_id IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_tasks_not_self_parent",
            "parent_id IS NULL OR parent_id <> id",
        )
        batch_op.create_check_constraint("ck_tasks_level", "level >= 0 AND level <= 2")
        batch_op.create_check_constraint(
            "ck_tasks_progress",
            "(progress_enabled = 0 AND progress_percent IS NULL) OR "
            "(progress_enabled = 1 AND progress_percent >= 0 "
            "AND progress_percent <= 100 AND progress_percent % 5 = 0)",
        )
        batch_op.create_index(
            "ix_tasks_department_work_id",
            ["department_work_id"],
        )
        batch_op.create_index("ix_tasks_parent_id", ["parent_id"])
        batch_op.create_index(
            "ix_tasks_department_work_status",
            ["department_work_id", "status"],
        )
        batch_op.create_index("ix_tasks_due_status", ["due_date", "status"])


def _create_task_progress_history() -> None:
    op.create_table(
        "task_progress_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("from_enabled", sa.Boolean(), nullable=False),
        sa.Column("to_enabled", sa.Boolean(), nullable=False),
        sa.Column("from_percent", sa.Integer(), nullable=True),
        sa.Column("to_percent", sa.Integer(), nullable=True),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=36), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "((from_enabled = 0 AND from_percent IS NULL) OR "
            "(from_enabled = 1 AND from_percent >= 0 "
            "AND from_percent <= 100 AND from_percent % 5 = 0)) AND "
            "((to_enabled = 0 AND to_percent IS NULL) OR "
            "(to_enabled = 1 AND to_percent >= 0 "
            "AND to_percent <= 100 AND to_percent % 5 = 0))",
            name="ck_task_progress_history_percent",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_progress_history_task_id",
        "task_progress_history",
        ["task_id"],
    )
    op.create_index(
        "ix_task_progress_history_task_time",
        "task_progress_history",
        ["task_id", "changed_at"],
    )


def _rebuild_work_records() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_work_records_minutes_insert"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_work_records_minutes_update"))
    with op.batch_alter_table("work_records", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("department_work_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_work_records_department_work_id_department_works",
            "department_works",
            ["department_work_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_work_records_at_most_one_source",
            "project_id IS NULL OR department_work_id IS NULL",
        )
        batch_op.create_index(
            "ix_work_records_department_work_id",
            ["department_work_id"],
        )
        batch_op.create_index(
            "ix_work_records_department_work_date",
            ["department_work_id", "work_date"],
        )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text(_MINUTES_INSERT_TRIGGER))
        op.execute(sa.text(_MINUTES_UPDATE_TRIGGER))


def _rebuild_deliverables() -> None:
    with op.batch_alter_table("deliverables", recreate="always") as batch_op:
        batch_op.alter_column(
            "project_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("department_work_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_deliverables_department_work_id_department_works",
            "department_works",
            ["department_work_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_deliverables_exactly_one_work_source",
            "(project_id IS NOT NULL AND department_work_id IS NULL) OR "
            "(project_id IS NULL AND department_work_id IS NOT NULL)",
        )
        batch_op.create_index(
            "ix_deliverables_department_work_id",
            ["department_work_id"],
        )


def _create_work_record_creation_requests() -> None:
    op.create_table(
        "work_record_creation_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("work_record_id", sa.String(length=36), nullable=False),
        sa.Column("created_project_id", sa.String(length=36), nullable=True),
        sa.Column("created_department_work_id", sa.String(length=36), nullable=True),
        sa.Column("created_task_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_department_work_id"],
            ["department_works.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_task_id"],
            ["tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_record_id"],
            ["work_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id",
            "idempotency_key",
            name="uq_work_record_creation_actor_key",
        ),
    )


def _rebuild_team_weekly_summaries() -> None:
    op.add_column(
        "team_weekly_summaries",
        sa.Column("included_leader_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "team_weekly_summaries",
        sa.Column("source_reports", sa.JSON(), nullable=True),
    )
    summaries = sa.table(
        "team_weekly_summaries",
        sa.column("included_leader_count", sa.Integer()),
    )
    op.execute(summaries.update().values(included_leader_count=0))

    with op.batch_alter_table("team_weekly_summaries", recreate="always") as batch_op:
        batch_op.alter_column(
            "included_leader_count",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_team_weekly_summaries_leader_count",
            "included_leader_count >= 0 AND included_leader_count <= submitted_count",
        )


def _upgrade_schema() -> None:
    _create_departments()
    _add_user_department()
    _create_department_works()
    _rebuild_tasks()
    _create_task_progress_history()
    _rebuild_work_records()
    _rebuild_deliverables()
    _create_work_record_creation_requests()
    _rebuild_team_weekly_summaries()


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _run_sqlite_schema_transaction(_upgrade_schema)
    else:
        _upgrade_schema()


def _assert_downgrade_is_lossless() -> None:
    checks = {
        "department rows": "SELECT COUNT(*) FROM departments",
        "department work rows": "SELECT COUNT(*) FROM department_works",
        "department assignments": (
            "SELECT COUNT(*) FROM users WHERE primary_department_id IS NOT NULL"
        ),
        "department-sourced tasks": (
            "SELECT COUNT(*) FROM tasks WHERE department_work_id IS NOT NULL"
        ),
        "nested tasks": "SELECT COUNT(*) FROM tasks WHERE parent_id IS NOT NULL OR level != 0",
        "task progress": (
            "SELECT COUNT(*) FROM tasks "
            "WHERE progress_enabled != 0 OR progress_percent IS NOT NULL"
        ),
        "task progress history": "SELECT COUNT(*) FROM task_progress_history",
        "department-sourced work records": (
            "SELECT COUNT(*) FROM work_records WHERE department_work_id IS NOT NULL"
        ),
        "department-sourced deliverables": (
            "SELECT COUNT(*) FROM deliverables WHERE department_work_id IS NOT NULL"
        ),
        "idempotency records": "SELECT COUNT(*) FROM work_record_creation_requests",
        "team summary source metadata": (
            "SELECT COUNT(*) FROM team_weekly_summaries "
            "WHERE included_leader_count != 0 OR source_reports IS NOT NULL"
        ),
    }
    populated = [
        label
        for label, statement in checks.items()
        if op.get_bind().execute(sa.text(statement)).scalar_one()
    ]
    if populated:
        raise RuntimeError(
            "downgrade would discard workflow data: " + ", ".join(populated)
        )


def _downgrade_schema() -> None:
    _assert_downgrade_is_lossless()

    with op.batch_alter_table("team_weekly_summaries", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_team_weekly_summaries_leader_count",
            type_="check",
        )
        batch_op.drop_column("source_reports")
        batch_op.drop_column("included_leader_count")

    op.drop_table("work_record_creation_requests")

    with op.batch_alter_table("deliverables", recreate="always") as batch_op:
        batch_op.drop_index("ix_deliverables_department_work_id")
        batch_op.drop_constraint(
            "ck_deliverables_exactly_one_work_source",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_deliverables_department_work_id_department_works",
            type_="foreignkey",
        )
        batch_op.drop_column("department_work_id")
        batch_op.alter_column(
            "project_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )

    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_work_records_minutes_insert"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_work_records_minutes_update"))
    with op.batch_alter_table("work_records", recreate="always") as batch_op:
        batch_op.drop_index("ix_work_records_department_work_date")
        batch_op.drop_index("ix_work_records_department_work_id")
        batch_op.drop_constraint(
            "ck_work_records_at_most_one_source",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_work_records_department_work_id_department_works",
            type_="foreignkey",
        )
        batch_op.drop_column("department_work_id")
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text(_MINUTES_INSERT_TRIGGER))
        op.execute(sa.text(_MINUTES_UPDATE_TRIGGER))

    op.drop_table("task_progress_history")

    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.drop_index("ix_tasks_due_status")
        batch_op.drop_index("ix_tasks_department_work_status")
        batch_op.drop_index("ix_tasks_parent_id")
        batch_op.drop_index("ix_tasks_department_work_id")
        batch_op.drop_constraint("ck_tasks_progress", type_="check")
        batch_op.drop_constraint("ck_tasks_level", type_="check")
        batch_op.drop_constraint("ck_tasks_not_self_parent", type_="check")
        batch_op.drop_constraint("ck_tasks_exactly_one_source", type_="check")
        batch_op.drop_constraint(
            "fk_tasks_parent_id_tasks",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_tasks_department_work_id_department_works",
            type_="foreignkey",
        )
        batch_op.drop_column("progress_percent")
        batch_op.drop_column("progress_enabled")
        batch_op.drop_column("level")
        batch_op.drop_column("parent_id")
        batch_op.drop_column("department_work_id")
        batch_op.alter_column(
            "project_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )

    op.drop_index("ix_department_works_department_status_deleted", table_name="department_works")
    op.drop_index("uq_department_works_department_name_active", table_name="department_works")
    op.drop_index("ix_department_works_owner_id", table_name="department_works")
    op.drop_index("ix_department_works_department_id", table_name="department_works")
    op.drop_table("department_works")

    op.drop_index("ix_users_primary_department_id", table_name="users")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("users", recreate="always") as batch_op:
            batch_op.drop_constraint(
                "fk_users_primary_department_id_departments",
                type_="foreignkey",
            )
            batch_op.drop_column("primary_department_id")
    else:
        op.drop_constraint(
            "fk_users_primary_department_id_departments",
            "users",
            type_="foreignkey",
        )
        op.drop_column("users", "primary_department_id")

    op.drop_index("ix_departments_active_deleted", table_name="departments")
    op.drop_index("uq_departments_normalized_name_active", table_name="departments")
    op.drop_index("ix_departments_leader_id", table_name="departments")
    op.drop_table("departments")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _run_sqlite_schema_transaction(_downgrade_schema)
    else:
        _downgrade_schema()
