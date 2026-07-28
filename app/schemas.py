from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator

from app.models import ProjectStatus, TaskPriority, TaskStatus, UserRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    login_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class UserOut(ORMModel):
    id: str
    login_name: str
    display_name: str
    role: str
    leader_id: str | None
    avatar_key: str | None
    is_active: bool
    must_change_password: bool
    revision: int


class AuthContextOut(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None
    details: dict[str, Any] | None


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=256)
    role: UserRole = UserRole.MEMBER


class UserLeaderUpdate(BaseModel):
    revision: int = Field(ge=1)
    leader_id: str | None = None


class UserUpdate(BaseModel):
    revision: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    leader_id: str | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=5, max_length=256)


class AvatarOptionOut(BaseModel):
    id: str
    label: str
    style: str
    style_label: str
    character: int
    url: str


class ProfileAvatarUpdate(BaseModel):
    revision: int = Field(ge=1)
    avatar_key: str | None = Field(default=None, max_length=40)


class ProjectTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, max_length=24)
    sort_order: int = Field(default=0, ge=-10000, le=10000)


class ProjectTagUpdate(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, max_length=24)
    sort_order: int | None = Field(default=None, ge=-10000, le=10000)
    is_active: bool | None = None


class ProjectTagOut(ORMModel):
    id: str
    name: str
    description: str | None
    color: str | None
    sort_order: int
    is_active: bool
    revision: int


class ProjectAliasOut(ORMModel):
    id: str
    value: str
    source: str
    created_at: datetime


class ProjectMemberOut(BaseModel):
    user_id: str
    display_name: str
    avatar_key: str | None = None
    role: str
    joined_at: datetime
    left_at: datetime | None


class ProjectSummaryOut(ORMModel):
    id: str
    code: str
    name: str
    status: str
    parent_project_id: str | None
    owner_id: str
    owner_display_name: str = ""
    owner_avatar_key: str | None = None
    planned_start_date: date | None
    planned_end_date: date | None
    revision: int
    created_at: datetime
    updated_at: datetime
    tags: list[ProjectTagOut] = []


class ProjectOut(ProjectSummaryOut):
    description: str | None
    proposed_by: str
    approved_by: str | None
    approved_at: datetime | None
    rejected_reason: str | None
    merged_into_project_id: str | None
    aliases: list[ProjectAliasOut] = []
    members: list[ProjectMemberOut] = []


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    parent_project_id: str | None = None
    owner_id: str | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    tag_ids: list[str] = Field(default_factory=list, max_length=50)
    allow_similar_name: bool = False

    @field_validator("tag_ids")
    @classmethod
    def unique_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ProjectUpdate(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    parent_project_id: str | None = None
    owner_id: str | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None


class RevisionAction(BaseModel):
    revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class ProjectTransition(RevisionAction):
    status: ProjectStatus


class ProjectAliasCreate(BaseModel):
    revision: int = Field(ge=1)
    value: str = Field(min_length=1, max_length=200)


class ProjectMemberAdd(BaseModel):
    revision: int = Field(ge=1)
    user_id: str


class ProjectTagAssign(BaseModel):
    revision: int = Field(ge=1)
    tag_id: str


class DuplicateCandidate(BaseModel):
    project_id: str
    code: str
    name: str
    matched_value: str
    match_type: str
    similarity: float
    status: str


class ProjectMergeRequest(BaseModel):
    source_revision: int = Field(ge=1)
    target_project_id: str
    target_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class ProjectMergePreview(BaseModel):
    source_project_id: str
    target_project_id: str
    source_name: str
    target_name: str
    task_count: int
    work_record_count: int
    deliverable_count: int
    child_project_count: int
    new_member_count: int
    new_tag_count: int
    aliases_to_move: list[str]


class ProjectMergeOut(BaseModel):
    merge_id: str
    source_project_id: str
    target_project_id: str
    moved_counts: dict[str, int]


class TaskCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10000)
    owner_id: str
    collaborator_ids: list[str] = Field(default_factory=list, max_length=100)
    priority: TaskPriority = TaskPriority.P1
    due_date: date | None = None

    @field_validator("collaborator_ids")
    @classmethod
    def unique_collaborators(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class TaskUpdate(BaseModel):
    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10000)
    priority: TaskPriority | None = None
    due_date: date | None = None
    collaborator_ids: list[str] | None = Field(default=None, max_length=100)


class TaskTransition(BaseModel):
    revision: int = Field(ge=1)
    status: TaskStatus
    blocker_reason: str | None = Field(default=None, max_length=4000)
    result: str | None = Field(default=None, max_length=10000)
    cancel_reason: str | None = Field(default=None, max_length=4000)


class TaskReassign(BaseModel):
    revision: int = Field(ge=1)
    owner_id: str
    reason: str | None = Field(default=None, max_length=2000)


class TaskOut(ORMModel):
    id: str
    project_id: str
    title: str
    description: str | None
    owner_id: str
    created_by: str
    priority: str
    status: str
    due_date: date | None
    blocker_reason: str | None
    result: str | None
    cancel_reason: str | None
    started_at: datetime | None
    completed_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime
    collaborator_ids: list[str] = []


class DeliverableInput(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    url: HttpUrl


class DeliverableOut(ORMModel):
    id: str
    project_id: str
    task_id: str | None
    work_record_id: str | None
    name: str
    url: str
    revision: int
    created_at: datetime


class WorkRecordCreate(BaseModel):
    work_date: date
    content: str = Field(min_length=1, max_length=20000)
    minutes: int = Field(ge=30, le=1440, multiple_of=30)
    project_id: str | None = None
    task_id: str | None = None
    risk: str | None = Field(default=None, max_length=5000)
    next_action: str | None = Field(default=None, max_length=5000)
    deliverables: list[DeliverableInput] = Field(default_factory=list, max_length=50)


class WorkRecordUpdate(BaseModel):
    revision: int = Field(ge=1)
    work_date: date | None = None
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    minutes: int | None = Field(default=None, ge=30, le=1440, multiple_of=30)
    project_id: str | None = None
    task_id: str | None = None
    risk: str | None = Field(default=None, max_length=5000)
    next_action: str | None = Field(default=None, max_length=5000)
    delegated_edit_reason: str | None = Field(default=None, max_length=2000)


class WorkRecordOut(ORMModel):
    id: str
    author_id: str
    author_display_name: str = ""
    author_avatar_key: str | None = None
    work_date: date
    content: str
    minutes: int
    project_id: str | None
    task_id: str | None
    risk: str | None
    next_action: str | None
    last_edited_by: str
    last_editor_display_name: str = ""
    last_editor_avatar_key: str | None = None
    delegated_edit_reason: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    deliverables: list[DeliverableOut] = []


class WeeklyReportOut(ORMModel):
    id: str
    author_id: str
    week_start: date
    week_end: date
    content: str
    submitted_content: str | None
    submitted_to_id: str | None
    generated_at: datetime | None
    generation_model: str | None
    generation_usage: dict[str, int] | None
    submitted_at: datetime | None
    submission_version: int
    revision: int
    created_at: datetime
    updated_at: datetime
    has_unsubmitted_changes: bool


class WeeklyReportCurrentOut(BaseModel):
    week_start: date
    week_end: date
    report: WeeklyReportOut | None


class WeeklyReportDraftUpdate(BaseModel):
    revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=50000)


class WeeklyReportSubmit(BaseModel):
    revision: int = Field(ge=1)
    overwrite_confirmed: bool = False


class WeeklyReportInboxOut(BaseModel):
    id: str
    author_id: str
    author_display_name: str
    week_start: date
    week_end: date
    content: str
    submitted_at: datetime
    submission_version: int


class AuditEventOut(ORMModel):
    id: str
    request_id: str | None
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    result: str
    detail: dict[str, Any] | None
    client_ip: str | None
    created_at: datetime


class AIStatusOut(BaseModel):
    configured: bool
    provider: str
    model: str


class AIChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)


class AIChatOut(BaseModel):
    answer: str
    model: str
    usage: dict[str, int]


class AIProviderAccessModeOut(BaseModel):
    id: str
    name: str
    description: str
    base_url: str
    protocol: str
    default_model: str
    models: list[str]
    docs_url: str


class AIProviderOptionOut(BaseModel):
    id: str
    name: str
    default_access_mode: str
    access_modes: list[AIProviderAccessModeOut]
    api_key_url: str


class AIConfigurationOut(BaseModel):
    configured: bool
    source: str
    provider: str | None
    provider_name: str | None
    access_mode: str | None
    access_mode_name: str | None
    protocol: str | None
    base_url: str | None
    model: str | None
    api_key_hint: str | None
    tested_at: datetime | None
    updated_at: datetime | None
    revision: int | None
    encryption_ready: bool


class AIConfigurationTestRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    access_mode: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=120)
    api_key: SecretStr

    @field_validator("provider", "access_mode", "model")
    @classmethod
    def strip_ai_test_fields(cls, value: str) -> str:
        return value.strip()


class AIConfigurationTestOut(BaseModel):
    success: bool
    provider: str
    access_mode: str
    model: str
    message: str
    usage: dict[str, int]
    verification_token: str
    expires_at: datetime


class AIConfigurationSaveRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    access_mode: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=120)
    api_key: SecretStr
    verification_token: str = Field(min_length=20, max_length=4096)
    revision: int | None = Field(default=None, ge=1)

    @field_validator("provider", "access_mode", "model", "verification_token")
    @classmethod
    def strip_ai_save_fields(cls, value: str) -> str:
        return value.strip()
