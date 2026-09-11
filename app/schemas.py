from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

from app.models import (
    AttentionStatus,
    BusinessStage,
    ChangelogCategory,
    DepartmentWorkStatus,
    DepartmentWorkVisibility,
    PermissionKey,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
)


def _strip_required_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("不能只包含空格")
    return stripped


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    login_name: str = Field(
        min_length=1,
        max_length=120,
        description="登录名或显示名称",
    )
    password: str = Field(min_length=1, max_length=256)

    @field_validator("login_name")
    @classmethod
    def strip_login_identifier(cls, value: str) -> str:
        return _strip_required_text(value)


class UserOut(ORMModel):
    id: str
    login_name: str
    display_name: str
    role: str
    leader_id: str | None
    primary_department_id: str | None
    avatar_key: str | None
    is_active: bool
    must_change_password: bool
    revision: int


class UserCandidateOut(ORMModel):
    """Minimum user fields exposed for business assignment pickers."""

    id: str
    display_name: str
    avatar_key: str | None
    primary_department_id: str | None


class AuthContextOut(BaseModel):
    user: UserOut
    permissions: list[str]
    csrf_token: str
    expires_at: datetime


class PermissionDefinitionOut(BaseModel):
    key: str
    group: str
    group_label: str
    label: str
    description: str
    system_admin_assignable: bool
    requires_team_scope: bool


class UserPermissionsOut(BaseModel):
    user_id: str
    revision: int
    assigned_permissions: list[str]
    effective_permissions: list[str]


class UserPermissionsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    permissions: list[PermissionKey] = Field(default_factory=list)


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
    primary_department_id: str | None = None

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        return _strip_required_text(value)


class UserLeaderUpdate(BaseModel):
    revision: int = Field(ge=1)
    leader_id: str | None = None


class UserUpdate(BaseModel):
    revision: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    leader_id: str | None = None
    primary_department_id: str | None = None

    @field_validator("display_name")
    @classmethod
    def strip_optional_display_name(cls, value: str | None) -> str | None:
        return _strip_required_text(value) if value is not None else None


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


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    leader_id: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip_required_text(value)


class DepartmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    leader_id: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        return _strip_required_text(value) if value is not None else None


class DepartmentOut(ORMModel):
    id: str
    name: str
    leader_id: str | None
    is_active: bool
    created_by: str
    revision: int
    created_at: datetime
    updated_at: datetime


class DepartmentWorkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    department_id: str | None = None
    owner_id: str | None = None
    visibility: DepartmentWorkVisibility = DepartmentWorkVisibility.DEPARTMENT_ONLY

    @field_validator("name")
    @classmethod
    def strip_work_name(cls, value: str) -> str:
        return _strip_required_text(value)


class DepartmentWorkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    owner_id: str | None = None
    visibility: DepartmentWorkVisibility | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_work_name(cls, value: str | None) -> str | None:
        return _strip_required_text(value) if value is not None else None


class DepartmentWorkTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    status: DepartmentWorkStatus


class DepartmentWorkOut(ORMModel):
    id: str
    code: str
    name: str
    description: str | None
    department_id: str
    department_name: str = ""
    owner_id: str
    owner_display_name: str = ""
    status: str
    visibility: str
    created_by: str
    revision: int
    created_at: datetime
    updated_at: datetime


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


class OpportunityMemberOut(BaseModel):
    id: str
    display_name: str
    avatar_key: str | None


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    customer_name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    owner_id: str | None = None
    member_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("member_ids")
    @classmethod
    def unique_members(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class OpportunityProgressCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    week_start: date
    business_stage: BusinessStage
    attention_status: AttentionStatus
    progress_percent: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=10000)
    output_summary: str | None = Field(default=None, max_length=10000)

    @field_validator("week_start")
    @classmethod
    def week_must_start_on_monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("week_start 必须是周一")
        return value


class OpportunityProgressOut(ORMModel):
    id: str
    opportunity_id: str
    week_start: date
    business_stage: str
    attention_status: str
    progress_percent: int
    summary: str
    output_summary: str | None
    created_by: str
    created_at: datetime
    revision: int


class OpportunityOut(ORMModel):
    id: str
    code: str
    name: str
    customer_name: str | None
    description: str | None
    owner_id: str
    owner_display_name: str = ""
    owner_avatar_key: str | None = None
    status: str
    business_stage: str
    attention_status: str
    progress_percent: int
    linked_project_id: str | None
    linked_project_code: str | None = None
    linked_project_name: str | None = None
    linked_project_status: str | None = None
    project_linked_at: datetime | None
    members: list[OpportunityMemberOut] = []
    can_manage: bool = False
    can_convert: bool = False
    revision: int
    created_at: datetime
    updated_at: datetime


class OpportunityConvertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    project: ProjectCreate


class OpportunityConversionOut(BaseModel):
    opportunity_id: str
    opportunity_revision: int
    project: ProjectOut


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
    progress_count: int
    invalidated_task_relation_count: int
    child_project_count: int
    new_member_count: int
    new_tag_count: int
    aliases_to_move: list[str]


class ProjectMergeOut(BaseModel):
    merge_id: str
    source_project_id: str
    target_project_id: str
    moved_counts: dict[str, int]


class TaskTimeScope(StrEnum):
    TODAY = "today"
    WEEK = "week"
    ALL = "all"


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    department_work_id: str | None = None
    parent_id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10000)
    owner_id: str | None = None
    collaborator_ids: list[str] = Field(default_factory=list, max_length=100)
    priority: TaskPriority = TaskPriority.P1
    due_date: date | None = None

    @field_validator("collaborator_ids")
    @classmethod
    def unique_collaborators(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_source(self) -> TaskCreate:
        source_count = int(self.project_id is not None) + int(
            self.department_work_id is not None
        )
        if self.parent_id:
            if source_count > 1:
                raise ValueError("项目和部门工作不能同时作为任务来源")
        elif source_count != 1:
            raise ValueError("任务必须且只能选择项目或部门工作之一")
        return self


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
    complete_descendants: bool = False


class TaskReassign(BaseModel):
    revision: int = Field(ge=1)
    owner_id: str
    reason: str | None = Field(default=None, max_length=2000)


class TaskOut(ORMModel):
    id: str
    project_id: str | None
    department_work_id: str | None
    parent_id: str | None
    level: int
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
    progress_enabled: bool
    progress_percent: int | None
    revision: int
    created_at: datetime
    updated_at: datetime
    collaborator_ids: list[str] = []


class TaskProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    enabled: bool
    percent: int | None = Field(default=None, ge=0, le=100, multiple_of=5)
    result: str | None = Field(default=None, max_length=10000)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_enabled_percent(self) -> TaskProgressUpdate:
        if self.enabled and self.percent is None:
            raise ValueError("开启进度跟踪时必须提供进度")
        if not self.enabled and self.percent is not None:
            raise ValueError("关闭进度跟踪时不能提供进度")
        return self


class TaskProgressHistoryOut(ORMModel):
    id: str
    task_id: str
    from_enabled: bool
    to_enabled: bool
    from_percent: int | None
    to_percent: int | None
    from_status: str
    to_status: str
    reason: str | None
    changed_by: str
    changed_at: datetime


class TaskTreeDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class ProjectProgressCreate(BaseModel):
    week_start: date
    business_stage: BusinessStage
    attention_status: AttentionStatus
    progress_percent: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=10000)
    output_summary: str | None = Field(default=None, max_length=10000)

    @field_validator("week_start")
    @classmethod
    def week_must_start_on_monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("week_start 必须是周一")
        return value


class ProjectProgressOut(ORMModel):
    id: str
    project_id: str
    week_start: date
    business_stage: str
    attention_status: str
    progress_percent: int
    summary: str
    output_summary: str | None
    created_by: str
    created_at: datetime
    revision: int


class TaskRelationCreate(BaseModel):
    source_task_id: str
    target_task_id: str
    label: str = Field(min_length=1, max_length=240)


class TaskRelationOut(ORMModel):
    id: str
    source_task_id: str
    target_task_id: str
    label: str
    created_at: datetime


class DeliverableInput(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    url: HttpUrl


class DeliverableOut(ORMModel):
    id: str
    project_id: str | None
    department_work_id: str | None
    task_id: str | None
    work_record_id: str | None
    name: str
    url: str
    revision: int
    created_at: datetime


class TimeBlockInput(BaseModel):
    start: int = Field(ge=0, lt=1440, multiple_of=30)
    end: int = Field(gt=0, le=1440, multiple_of=30)

    @model_validator(mode="after")
    def validate_order(self) -> TimeBlockInput:
        if self.end <= self.start:
            raise ValueError("时间块结束必须晚于开始")
        return self


class TimeBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: int = Field(validation_alias=AliasChoices("start", "start_minute"))
    end: int = Field(validation_alias=AliasChoices("end", "end_minute"))


def _validate_time_blocks(
    blocks: list[TimeBlockInput] | None,
) -> list[TimeBlockInput] | None:
    if blocks is None:
        return None
    ordered = sorted(blocks, key=lambda block: (block.start, block.end))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.start < previous.end:
            raise ValueError("时间块之间不得重叠")
        if current.start == previous.end:
            raise ValueError("相邻时间块必须先合并")
    return blocks


class WorkRecordCreate(BaseModel):
    work_date: date
    content: str = Field(min_length=1, max_length=20000)
    minutes: int = Field(ge=30, le=1440, multiple_of=30)
    project_id: str | None = None
    department_work_id: str | None = None
    task_id: str | None = None
    risk: str | None = Field(default=None, max_length=5000)
    next_action: str | None = Field(default=None, max_length=5000)
    deliverables: list[DeliverableInput] = Field(default_factory=list, max_length=50)
    time_blocks: list[TimeBlockInput] = Field(default_factory=list, max_length=24)

    @field_validator("time_blocks")
    @classmethod
    def validate_time_blocks(cls, value: list[TimeBlockInput]) -> list[TimeBlockInput]:
        return _validate_time_blocks(value) or []

    @model_validator(mode="after")
    def validate_source(self) -> WorkRecordCreate:
        if self.project_id and self.department_work_id:
            raise ValueError("工作记录不能同时关联项目和部门工作")
        return self


class WorkRecordUpdate(BaseModel):
    revision: int = Field(ge=1)
    work_date: date | None = None
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    minutes: int | None = Field(default=None, ge=30, le=1440, multiple_of=30)
    project_id: str | None = None
    department_work_id: str | None = None
    task_id: str | None = None
    risk: str | None = Field(default=None, max_length=5000)
    next_action: str | None = Field(default=None, max_length=5000)
    delegated_edit_reason: str | None = Field(default=None, max_length=2000)
    time_blocks: list[TimeBlockInput] | None = Field(default=None, max_length=24)

    @field_validator("time_blocks")
    @classmethod
    def validate_time_blocks(
        cls,
        value: list[TimeBlockInput] | None,
    ) -> list[TimeBlockInput] | None:
        return _validate_time_blocks(value)

    @model_validator(mode="after")
    def validate_update_source(self) -> WorkRecordUpdate:
        if self.project_id and self.department_work_id:
            raise ValueError("工作记录不能同时关联项目和部门工作")
        return self


class WorkRecordOut(ORMModel):
    id: str
    author_id: str
    author_display_name: str = ""
    author_avatar_key: str | None = None
    work_date: date
    content: str
    minutes: int
    project_id: str | None
    project_name: str | None = None
    department_work_id: str | None
    department_work_name: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    source_name: str | None = None
    task_id: str | None
    task_title: str | None = None
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
    time_blocks: list[TimeBlockOut] = Field(default_factory=list)


class QuickTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10000)
    owner_id: str | None = None
    collaborator_ids: list[str] = Field(default_factory=list, max_length=100)
    priority: TaskPriority = TaskPriority.P1
    due_date: date | None = None
    parent_id: str | None = None

    @field_validator("collaborator_ids")
    @classmethod
    def unique_quick_collaborators(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class WorkRecordQuickCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=80)
    work_date: date
    content: str = Field(min_length=1, max_length=20000)
    minutes: int = Field(ge=30, le=1440, multiple_of=30)
    risk: str | None = Field(default=None, max_length=5000)
    next_action: str | None = Field(default=None, max_length=5000)
    deliverables: list[DeliverableInput] = Field(default_factory=list, max_length=50)
    time_blocks: list[TimeBlockInput] = Field(default_factory=list, max_length=24)
    project_id: str | None = None
    department_work_id: str | None = None
    new_project: ProjectCreate | None = None
    new_department_work: DepartmentWorkCreate | None = None
    task_id: str | None = None
    new_task: QuickTaskCreate | None = None

    @field_validator("time_blocks")
    @classmethod
    def validate_time_blocks(cls, value: list[TimeBlockInput]) -> list[TimeBlockInput]:
        return _validate_time_blocks(value) or []

    @model_validator(mode="after")
    def validate_composite_choices(self) -> WorkRecordQuickCreate:
        source_count = sum(
            int(value is not None)
            for value in (
                self.project_id,
                self.department_work_id,
                self.new_project,
                self.new_department_work,
            )
        )
        if source_count > 1:
            raise ValueError("一次只能选择或新建一个工作来源")
        if self.task_id and self.new_task:
            raise ValueError("已有任务和新任务不能同时提交")
        if self.new_task and source_count != 1 and not self.new_task.parent_id:
            raise ValueError("新建任务必须选择或新建一个工作来源")
        return self


class WorkRecordQuickCreateOut(BaseModel):
    work_record: WorkRecordOut
    created_project_id: str | None = None
    created_department_work_id: str | None = None
    created_task_id: str | None = None
    replayed: bool = False


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


class DashboardWeekOut(BaseModel):
    week_start: date
    week_end: date
    label: str
    is_current: bool


class DashboardMemberOut(BaseModel):
    id: str
    display_name: str
    role: str
    avatar_key: str | None
    submitted: bool
    submitted_at: datetime | None
    weekly_minutes: int | None
    submitted_weeks: list[date]


class DashboardWorkItemOut(BaseModel):
    id: str
    author_id: str
    author_display_name: str
    author_avatar_key: str | None
    content: str
    minutes: int
    risk: str | None
    next_action: str | None


class DashboardTaskOut(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    owner_id: str
    owner_display_name: str
    owner_avatar_key: str | None
    due_date: date | None
    blocker_reason: str | None
    result: str | None


class DashboardProjectMemberOut(BaseModel):
    id: str
    display_name: str
    avatar_key: str | None


class DashboardStageHistoryOut(BaseModel):
    id: str
    week_start: date
    business_stage: str
    progress_percent: int
    created_at: datetime


class DashboardProjectOut(BaseModel):
    id: str
    code: str
    name: str
    type_label: str
    can_manage: bool
    lifecycle_status: str
    business_stage: str
    attention_status: str
    progress_percent: int
    weekly_minutes: int | None
    work_summary: str
    output_summary: str
    has_week_progress: bool
    people: list[DashboardProjectMemberOut]
    tasks: list[DashboardTaskOut]
    work_items: list[DashboardWorkItemOut]
    stage_history: list[DashboardStageHistoryOut]


class DashboardOpportunityOut(BaseModel):
    id: str
    code: str
    name: str
    customer_name: str | None
    description: str | None
    owner_id: str
    owner_display_name: str
    owner_avatar_key: str | None
    can_manage: bool
    can_convert: bool
    status: str
    business_stage: str
    attention_status: str
    progress_percent: int
    work_summary: str
    output_summary: str
    has_week_progress: bool
    linked_project_id: str | None
    linked_project_code: str | None
    linked_project_name: str | None
    linked_project_status: str | None
    people: list[DashboardProjectMemberOut]
    stage_history: list[DashboardStageHistoryOut]
    revision: int


class DashboardDeliverableOut(BaseModel):
    id: str
    name: str
    url: str
    project_id: str
    project_name: str
    author_id: str | None
    author_display_name: str | None


class DashboardTaskLinkOut(BaseModel):
    id: str
    source_task_id: str
    target_task_id: str
    label: str


class DashboardMetricsOut(BaseModel):
    tracking_count: int
    focus_count: int
    stage_advanced_count: int
    deliverable_count: int
    coordinate_count: int
    total_minutes: int
    submitted_count: int
    member_count: int


class DashboardWeekTrendOut(BaseModel):
    week_start: date
    week_end: date
    total_minutes: int
    deliverable_count: int
    submitted_count: int
    member_count: int


class DashboardStageCountOut(BaseModel):
    business_stage: str
    count: int


class DashboardTimelineEventOut(BaseModel):
    id: str
    opportunity_id: str
    opportunity_name: str
    week_start: date
    business_stage: str
    attention_status: str
    summary: str
    created_at: datetime


class TeamWeeklySummaryOut(ORMModel):
    id: str
    week_start: date
    week_end: date
    content: str
    generated_by: str
    forced: bool
    submitted_count: int
    expected_count: int
    included_leader_count: int = 0
    source_reports: list[dict[str, Any]] | None = None
    generation_model: str
    generation_usage: dict[str, int] | None
    created_at: datetime
    revision: int


class TeamWeeklySummaryGenerate(BaseModel):
    force: bool = False


class DashboardOut(BaseModel):
    accessible_pages: list[str]
    selected_week: DashboardWeekOut
    weeks: list[DashboardWeekOut]
    metrics: DashboardMetricsOut
    members: list[DashboardMemberOut]
    opportunities: list[DashboardOpportunityOut]
    projects: list[DashboardProjectOut]
    deliverables: list[DashboardDeliverableOut]
    task_links: list[DashboardTaskLinkOut]
    trends: list[DashboardWeekTrendOut]
    stage_distribution: list[DashboardStageCountOut]
    stage_timeline: list[DashboardTimelineEventOut]
    latest_team_summary: TeamWeeklySummaryOut | None


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
    client_request_id: str | None = Field(default=None, min_length=8, max_length=64)


class AIChatOut(BaseModel):
    answer: str
    model: str
    usage: dict[str, int]


class AIChatHistoryMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AIChatHistoryOut(BaseModel):
    messages: list[AIChatHistoryMessageOut]


class AIChatHistoryClearOut(BaseModel):
    cleared: int


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


class ChangelogEntryOut(BaseModel):
    id: str
    occurred_at: datetime
    category: ChangelogCategory
    title: str
    body: str
    created_by: str
    created_by_name: str
    updated_by: str
    updated_by_name: str
    revision: int
    created_at: datetime
    updated_at: datetime


class ChangelogEntryCreate(BaseModel):
    occurred_at: datetime
    category: ChangelogCategory
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("title", "body")
    @classmethod
    def strip_changelog_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class ChangelogEntryUpdate(BaseModel):
    revision: int = Field(ge=1)
    occurred_at: datetime | None = None
    category: ChangelogCategory | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20000)

    @field_validator("title", "body")
    @classmethod
    def strip_optional_changelog_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped
