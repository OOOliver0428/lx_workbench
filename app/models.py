from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy import DateTime as SQLAlchemyDateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.types import TypeDecorator

from app.identity import normalize_user_identifier


def utc_now() -> datetime:
    return datetime.now(UTC)


class DateTime(TypeDecorator[datetime]):
    """Persist UTC and always restore timezone-aware datetimes.

    SQLite ignores ``timezone=True`` and returns naive values. Keeping this
    compatibility wrapper under the existing model type name avoids a schema
    migration while making every ORM-loaded timestamp unambiguously UTC.
    """

    impl = SQLAlchemyDateTime
    cache_ok = True

    def __init__(self, *, timezone: bool = True) -> None:
        super().__init__()
        self.timezone = timezone

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(
            SQLAlchemyDateTime(timezone=dialect.name != "sqlite")
        )

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    MEMBER = "member"
    TEAM_LEADER = "team_leader"
    SYSTEM_ADMIN = "system_admin"
    SUPER_ADMIN = "super_admin"


class PermissionKey(StrEnum):
    DASHBOARD_OPPORTUNITY_VIEW = "dashboard.opportunity.view"
    DASHBOARD_OPPORTUNITY_PROGRESS = "dashboard.opportunity.progress"
    DASHBOARD_OPPORTUNITY_CREATE = "dashboard.opportunity.create"
    DASHBOARD_WORK_VIEW = "dashboard.work.view"
    DASHBOARD_OVERVIEW_VIEW = "dashboard.overview.view"
    DASHBOARD_TEAM_SUMMARY = "dashboard.team_summary.generate"
    PROJECTS_VIEW = "projects.view"
    PROJECTS_EDIT = "projects.edit"
    PROJECTS_CREATE = "projects.create"
    TASKS_VIEW = "tasks.view"
    TASKS_EDIT = "tasks.edit"
    TASKS_CREATE = "tasks.create"
    WORK_RECORDS_VIEW = "work_records.view"
    WORK_RECORDS_MANAGE = "work_records.manage"
    WEEKLY_REPORTS_VIEW = "weekly_reports.view"
    WEEKLY_REPORTS_MANAGE = "weekly_reports.manage"
    AI_USE = "ai.use"
    USERS_MANAGE = "settings.users.manage"
    TAGS_MANAGE = "settings.tags.manage"
    AI_CONFIG_MANAGE = "settings.ai.manage"
    AUDIT_VIEW = "settings.audit.view"


class ProjectStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    REJECTED = "rejected"
    MERGED = "merged"


class OpportunityStatus(StrEnum):
    ACTIVE = "active"
    WON = "won"
    LOST = "lost"
    ARCHIVED = "archived"


class ProjectMemberRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"


class BusinessStage(StrEnum):
    LEAD = "lead"
    REQUIREMENT = "requirement"
    SOLUTION_EXCHANGE = "solution_exchange"
    SOLUTION_CONFIRM = "solution_confirm"
    POC = "poc"
    TENDER = "tender"
    WON = "won"


class AttentionStatus(StrEnum):
    FOCUS = "focus"
    STEADY = "steady"
    COORDINATE = "coordinate"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class RevisionMixin:
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, object]:
        # Keep the existing API-level revision checks for friendly error details,
        # while also making the database UPDATE itself conditional on the
        # originally loaded revision. This closes the race where two sessions
        # both passed ``assert_revision`` before either one committed.
        return {"version_id_col": cls.revision}


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class User(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_display_name_key", "display_name_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    login_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name_key: Mapped[str | None] = mapped_column(String(512))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=UserRole.MEMBER.value)
    leader_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    avatar_key: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def _normalize_user_identity(
    _mapper: object,
    _connection: object,
    user: User,
) -> None:
    user.login_name = normalize_user_identifier(user.login_name)
    user.display_name = user.display_name.strip()
    user.display_name_key = normalize_user_identifier(user.display_name)


class UserPermission(Base, TimestampMixin):
    __tablename__ = "user_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_key: Mapped[str] = mapped_column(String(80), nullable=False)
    granted_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "permission_key",
            name="uq_user_permissions_user_key",
        ),
    )


class AIProviderConfig(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "ai_provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="primary")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    access_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="standard", server_default="standard"
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hint: Mapped[str] = mapped_column(String(24), nullable=False)
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tested_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (Index("ix_auth_sessions_user_active", "user_id", "expires_at"),)


class ProjectTag(Base, TimestampMixin, RevisionMixin, SoftDeleteMixin):
    __tablename__ = "project_tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(24))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Project(Base, TimestampMixin, RevisionMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.PENDING.value
    )
    parent_project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        index=True,
    )
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    proposed_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    merged_into_project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
    )
    planned_start_date: Mapped[date | None] = mapped_column(Date)
    planned_end_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint(
            "parent_project_id IS NULL OR parent_project_id <> id",
            name="ck_projects_not_self_parent",
        ),
        CheckConstraint(
            "merged_into_project_id IS NULL OR merged_into_project_id <> id",
            name="ck_projects_not_self_merge",
        ),
        CheckConstraint(
            "planned_end_date IS NULL OR planned_start_date IS NULL "
            "OR planned_end_date >= planned_start_date",
            name="ck_projects_valid_dates",
        ),
        Index(
            "uq_projects_normalized_name_active",
            "normalized_name",
            unique=True,
            sqlite_where=text("deleted_at IS NULL AND status != 'merged'"),
        ),
        Index("ix_projects_status_deleted", "status", "deleted_at"),
    )


class Opportunity(Base, TimestampMixin, RevisionMixin, SoftDeleteMixin):
    """Commercial opportunity kept separate from delivery project master data."""

    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OpportunityStatus.ACTIVE.value
    )
    business_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default=BusinessStage.LEAD.value
    )
    attention_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AttentionStatus.STEADY.value
    )
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    linked_project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        unique=True,
        index=True,
    )
    project_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_opportunities_progress_percent",
        ),
        Index("ix_opportunities_status_deleted", "status", "deleted_at"),
    )


class OpportunityMember(Base):
    __tablename__ = "opportunity_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    added_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "opportunity_id",
            "user_id",
            name="uq_opportunity_members_opportunity_user",
        ),
    )


class OpportunityProgress(Base, TimestampMixin, RevisionMixin):
    """Append-only commercial progress facts for an opportunity."""

    __tablename__ = "opportunity_progress"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    business_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    attention_status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_opportunity_progress_percent",
        ),
        Index(
            "ix_opportunity_progress_opportunity_week_created",
            "opportunity_id",
            "week_start",
            "created_at",
        ),
    )


class ProjectAlias(Base):
    __tablename__ = "project_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(240), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ProjectMember(Base):
    __tablename__ = "project_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectMemberRole.MEMBER.value
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        Index("ix_project_members_user_active", "user_id", "left_at"),
    )


class ProjectTagAssignment(Base):
    __tablename__ = "project_tag_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("project_tags.id", ondelete="RESTRICT"),
        nullable=False,
    )
    added_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "tag_id", name="uq_project_tag_assignments"),
        Index("ix_project_tag_assignments_tag", "tag_id", "project_id"),
    )


class ProjectMerge(Base):
    __tablename__ = "project_merges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )
    target_project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    moved_counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    target_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    merged_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    merged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Task(Base, TimestampMixin, RevisionMixin, SoftDeleteMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default=TaskPriority.P1.value)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TaskStatus.TODO.value)
    due_date: Mapped[date | None] = mapped_column(Date)
    blocker_reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_tasks_project_status", "project_id", "status"),)


class TaskCollaborator(Base):
    __tablename__ = "task_collaborators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    added_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_collaborators"),)


class TaskAssignmentHistory(Base):
    __tablename__ = "task_assignment_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    previous_owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    new_owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ProjectProgress(Base, TimestampMixin, RevisionMixin):
    """Append-only weekly facts that drive the war-room project display."""

    __tablename__ = "project_progress"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    business_stage: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=BusinessStage.LEAD.value,
    )
    attention_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AttentionStatus.STEADY.value,
    )
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_project_progress_percent",
        ),
        Index(
            "ix_project_progress_project_week_created",
            "project_id",
            "week_start",
            "created_at",
        ),
    )


class TaskRelation(Base, TimestampMixin, RevisionMixin, SoftDeleteMixin):
    """A named cross-project link between two task nodes in the graph."""

    __tablename__ = "task_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "source_task_id <> target_task_id",
            name="ck_task_relations_distinct_tasks",
        ),
        UniqueConstraint(
            "source_task_id",
            "target_task_id",
            name="uq_task_relations_pair",
        ),
    )


class WorkRecord(Base, TimestampMixin, RevisionMixin, SoftDeleteMixin):
    __tablename__ = "work_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="RESTRICT"),
        index=True,
    )
    risk: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    last_edited_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    delegated_edit_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "minutes >= 30 AND minutes <= 1440 AND minutes % 30 = 0",
            name="ck_work_records_minutes",
        ),
        Index("ix_work_records_project_date", "project_id", "work_date"),
    )


class WeeklyReport(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "weekly_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_content: Mapped[str | None] = mapped_column(Text)
    submitted_to_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_model: Mapped[str | None] = mapped_column(String(120))
    generation_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("author_id", "week_start", name="uq_weekly_reports_author_week"),
        CheckConstraint("week_end >= week_start", name="ck_weekly_reports_valid_week"),
        CheckConstraint(
            "submission_version >= 0",
            name="ck_weekly_reports_submission_version",
        ),
        Index(
            "ix_weekly_reports_recipient_submitted",
            "submitted_to_id",
            "submitted_at",
        ),
    )

    @property
    def has_unsubmitted_changes(self) -> bool:
        return self.submitted_content is None or self.content != self.submitted_content


class TeamWeeklySummary(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "team_weekly_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    forced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_model: Mapped[str] = mapped_column(String(120), nullable=False)
    generation_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint(
            "week_end >= week_start",
            name="ck_team_weekly_summaries_valid_week",
        ),
        CheckConstraint(
            "submitted_count >= 0 AND expected_count >= submitted_count",
            name="ck_team_weekly_summaries_counts",
        ),
        Index(
            "ix_team_weekly_summaries_week_created",
            "week_start",
            "created_at",
        ),
    )


class Deliverable(Base, TimestampMixin, RevisionMixin, SoftDeleteMixin):
    __tablename__ = "deliverables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="RESTRICT")
    )
    work_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("work_records.id", ondelete="RESTRICT"),
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(task_id IS NOT NULL AND work_record_id IS NULL) OR "
            "(task_id IS NULL AND work_record_id IS NOT NULL)",
            name="ck_deliverables_one_source",
        ),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    client_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_audit_entity_time", "entity_type", "entity_id", "created_at"),)
