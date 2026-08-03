"""add independent opportunities and conversion links

Revision ID: d2c7f4a9e601
Revises: c6e4b8a1d209
Create Date: 2026-07-31
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2c7f4a9e601"
down_revision: str | None = "c6e4b8a1d209"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGE_BY_STATUS = {
    "pending": ("lead", 8),
    "active": ("solution_exchange", 38),
    "paused": ("solution_confirm", 52),
    "completed": ("won", 100),
}


def _stable_id(kind: str, source_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mvp:{kind}:{source_id}"))


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=240), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("business_stage", sa.String(length=32), nullable=False),
        sa.Column("attention_status", sa.String(length=32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("linked_project_id", sa.String(length=36), nullable=True),
        sa.Column("project_linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_opportunities_progress_percent",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["linked_project_id"],
            ["projects.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        op.f("ix_opportunities_normalized_name"),
        "opportunities",
        ["normalized_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunities_owner_id"),
        "opportunities",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunities_linked_project_id"),
        "opportunities",
        ["linked_project_id"],
        unique=True,
    )
    op.create_index(
        "ix_opportunities_status_deleted",
        "opportunities",
        ["status", "deleted_at"],
        unique=False,
    )

    op.create_table(
        "opportunity_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("opportunity_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("added_by", sa.String(length=36), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "opportunity_id",
            "user_id",
            name="uq_opportunity_members_opportunity_user",
        ),
    )
    op.create_index(
        op.f("ix_opportunity_members_opportunity_id"),
        "opportunity_members",
        ["opportunity_id"],
        unique=False,
    )

    op.create_table(
        "opportunity_progress",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("opportunity_id", sa.String(length=36), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("business_stage", sa.String(length=32), nullable=False),
        sa.Column("attention_status", sa.String(length=32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_opportunity_progress_percent",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opportunity_progress_opportunity_id"),
        "opportunity_progress",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunity_progress_week_start"),
        "opportunity_progress",
        ["week_start"],
        unique=False,
    )
    op.create_index(
        "ix_opportunity_progress_opportunity_week_created",
        "opportunity_progress",
        ["opportunity_id", "week_start", "created_at"],
        unique=False,
    )

    connection = op.get_bind()
    projects = list(
        connection.execute(
            sa.text(
                """
                SELECT id, code, name, normalized_name, description, owner_id,
                       proposed_by, status, created_at, updated_at
                FROM projects
                WHERE deleted_at IS NULL
                  AND status IN ('pending', 'active', 'paused', 'completed')
                """
            )
        ).mappings()
    )
    progress_rows = list(
        connection.execute(
            sa.text(
                """
                SELECT *
                FROM project_progress
                ORDER BY project_id, week_start, created_at
                """
            )
        ).mappings()
    )
    latest_by_project = {row["project_id"]: row for row in progress_rows}
    opportunity_by_project: dict[str, str] = {}
    for project in projects:
        opportunity_id = _stable_id("opportunity", project["id"])
        opportunity_by_project[project["id"]] = opportunity_id
        latest = latest_by_project.get(project["id"])
        default_stage, default_percent = _STAGE_BY_STATUS[project["status"]]
        business_stage = latest["business_stage"] if latest else default_stage
        progress_percent = latest["progress_percent"] if latest else default_percent
        connection.execute(
            sa.text(
                """
                INSERT INTO opportunities (
                    id, code, name, normalized_name, customer_name, description,
                    owner_id, created_by, status, business_stage,
                    attention_status, progress_percent, linked_project_id,
                    project_linked_at, created_at, updated_at, revision,
                    deleted_at, deleted_by
                ) VALUES (
                    :id, :code, :name, :normalized_name, NULL, :description,
                    :owner_id, :created_by, :status, :business_stage,
                    :attention_status, :progress_percent, :linked_project_id,
                    :project_linked_at, :created_at, :updated_at, 1, NULL, NULL
                )
                """
            ),
            {
                "id": opportunity_id,
                "code": f"OPP-{uuid.UUID(opportunity_id).hex[:12].upper()}",
                "name": project["name"],
                "normalized_name": project["normalized_name"],
                "description": project["description"],
                "owner_id": project["owner_id"],
                "created_by": project["proposed_by"],
                "status": "won" if business_stage == "won" else "active",
                "business_stage": business_stage,
                "attention_status": (
                    latest["attention_status"] if latest else "steady"
                ),
                "progress_percent": progress_percent,
                "linked_project_id": project["id"],
                "project_linked_at": project["created_at"],
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
            },
        )

    memberships = list(
        connection.execute(
            sa.text(
                """
                SELECT id, project_id, user_id, added_by, joined_at
                FROM project_members
                WHERE left_at IS NULL
                """
            )
        ).mappings()
    )
    for membership in memberships:
        opportunity_id = opportunity_by_project.get(membership["project_id"])
        if not opportunity_id:
            continue
        connection.execute(
            sa.text(
                """
                INSERT INTO opportunity_members (
                    id, opportunity_id, user_id, added_by, added_at
                ) VALUES (
                    :id, :opportunity_id, :user_id, :added_by, :added_at
                )
                """
            ),
            {
                "id": _stable_id("opportunity-member", membership["id"]),
                "opportunity_id": opportunity_id,
                "user_id": membership["user_id"],
                "added_by": membership["added_by"],
                "added_at": membership["joined_at"],
            },
        )

    for progress in progress_rows:
        opportunity_id = opportunity_by_project.get(progress["project_id"])
        if not opportunity_id:
            continue
        connection.execute(
            sa.text(
                """
                INSERT INTO opportunity_progress (
                    id, opportunity_id, week_start, business_stage,
                    attention_status, progress_percent, summary,
                    output_summary, created_by, created_at, updated_at, revision
                ) VALUES (
                    :id, :opportunity_id, :week_start, :business_stage,
                    :attention_status, :progress_percent, :summary,
                    :output_summary, :created_by, :created_at, :updated_at,
                    :revision
                )
                """
            ),
            {
                "id": _stable_id("opportunity-progress", progress["id"]),
                "opportunity_id": opportunity_id,
                "week_start": progress["week_start"],
                "business_stage": progress["business_stage"],
                "attention_status": progress["attention_status"],
                "progress_percent": progress["progress_percent"],
                "summary": progress["summary"],
                "output_summary": progress["output_summary"],
                "created_by": progress["created_by"],
                "created_at": progress["created_at"],
                "updated_at": progress["updated_at"],
                "revision": progress["revision"],
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_opportunity_progress_opportunity_week_created",
        table_name="opportunity_progress",
    )
    op.drop_index(
        op.f("ix_opportunity_progress_week_start"),
        table_name="opportunity_progress",
    )
    op.drop_index(
        op.f("ix_opportunity_progress_opportunity_id"),
        table_name="opportunity_progress",
    )
    op.drop_table("opportunity_progress")
    op.drop_index(
        op.f("ix_opportunity_members_opportunity_id"),
        table_name="opportunity_members",
    )
    op.drop_table("opportunity_members")
    op.drop_index("ix_opportunities_status_deleted", table_name="opportunities")
    op.drop_index(
        op.f("ix_opportunities_linked_project_id"),
        table_name="opportunities",
    )
    op.drop_index(op.f("ix_opportunities_owner_id"), table_name="opportunities")
    op.drop_index(
        op.f("ix_opportunities_normalized_name"),
        table_name="opportunities",
    )
    op.drop_table("opportunities")
