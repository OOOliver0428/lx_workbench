from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.config import Settings
from app.domain import is_super_admin
from app.errors import AppError, ConflictError, PermissionDeniedError
from app.llm_guard import LLMGuard
from app.models import (
    AttentionStatus,
    BusinessStage,
    Deliverable,
    Opportunity,
    OpportunityMember,
    OpportunityProgress,
    OpportunityStatus,
    PermissionKey,
    Project,
    ProjectMember,
    ProjectProgress,
    ProjectStatus,
    ProjectTag,
    ProjectTagAssignment,
    Task,
    TaskCollaborator,
    TaskPriority,
    TaskRelation,
    TaskStatus,
    TeamWeeklySummary,
    User,
    UserRole,
    WeeklyReport,
    WorkRecord,
)
from app.schemas import (
    DashboardDeliverableOut,
    DashboardMemberOut,
    DashboardMetricsOut,
    DashboardOpportunityOut,
    DashboardOut,
    DashboardProjectMemberOut,
    DashboardProjectOut,
    DashboardStageCountOut,
    DashboardStageHistoryOut,
    DashboardTaskLinkOut,
    DashboardTaskOut,
    DashboardTimelineEventOut,
    DashboardWeekOut,
    DashboardWeekTrendOut,
    DashboardWorkItemOut,
    ManagementScopeOptionOut,
    ManagementScopeOut,
    ProjectProgressCreate,
    ProjectProgressOut,
    TaskRelationCreate,
    TaskRelationOut,
    TeamWeeklySummaryGenerate,
    TeamWeeklySummaryOut,
)
from app.services import ai as ai_service
from app.services import opportunities as opportunity_service
from app.services import permissions as permission_service
from app.services import projects as project_service
from app.services import tasks as task_service
from app.services.management_scope import (
    SCOPE_ALL_LED,
    SCOPE_DEPARTMENT,
    SCOPE_OTHER_DIRECT,
    normalize_scope_key,
    resolve_management_scope,
)

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
BUSINESS_USER_ROLES = {
    UserRole.MEMBER.value,
    UserRole.TEAM_LEADER.value,
}
TRACKED_PROJECT_STATUSES = {
    ProjectStatus.PENDING.value,
    ProjectStatus.ACTIVE.value,
    ProjectStatus.PAUSED.value,
    ProjectStatus.COMPLETED.value,
}
TRACKED_OPPORTUNITY_STATUSES = {
    OpportunityStatus.ACTIVE.value,
    OpportunityStatus.WON.value,
}
STAGE_ORDER = tuple(stage.value for stage in BusinessStage)
STAGE_BASE_PROGRESS = {
    BusinessStage.LEAD.value: 8,
    BusinessStage.REQUIREMENT.value: 20,
    BusinessStage.SOLUTION_EXCHANGE.value: 38,
    BusinessStage.SOLUTION_CONFIRM.value: 52,
    BusinessStage.POC.value: 68,
    BusinessStage.TENDER.value: 84,
    BusinessStage.WON.value: 100,
}
DEFAULT_STAGE_BY_PROJECT_STATUS = {
    ProjectStatus.PENDING.value: BusinessStage.LEAD.value,
    ProjectStatus.ACTIVE.value: BusinessStage.SOLUTION_EXCHANGE.value,
    ProjectStatus.PAUSED.value: BusinessStage.SOLUTION_CONFIRM.value,
    ProjectStatus.COMPLETED.value: BusinessStage.WON.value,
}

TEAM_SUMMARY_SYSTEM_PROMPT = """你是解决方案团队作战台的部门周报整理助手。
系统会提供指定自然周内、已正式提交的个人周报。
只能依据这些已提交内容汇总，不得补写不存在的项目、成果、工时、风险或计划。
保留明确的项目名称、成员、交付物、风险和下周行动；重复内容可以合并但不能改变事实。
只输出可直接复制的 Markdown 团队周报，不要输出解释、前言或代码围栏。"""

TEAM_SUMMARY_USER_PROMPT = """请生成团队周报，使用以下结构：
# 解决方案部门周报
## 本周总体概览
## 重点商机与项目进展
## 本周交付物
## 风险与待协调事项
## 下周重点
## 提交说明

“提交说明”需要准确写明本次汇总包含多少位成员；如非全员提交，明确列出缺失成员。"""


def normalize_week_start(value: date | None = None) -> date:
    local_date = value or datetime.now(SHANGHAI).date()
    return local_date - timedelta(days=local_date.weekday())


def week_out(week_start: date, *, current_week: date) -> DashboardWeekOut:
    week_end = week_start + timedelta(days=6)
    iso_year, iso_week, _weekday = week_start.isocalendar()
    return DashboardWeekOut(
        week_start=week_start,
        week_end=week_end,
        label=(
            f"{iso_year}-W{iso_week:02d}（{week_start:%m/%d}—{week_end:%m/%d}）"
        ),
        is_current=week_start == current_week,
    )


def accessible_pages(db: Session, actor: User) -> list[str]:
    page_permissions = (
        ("opp", PermissionKey.DASHBOARD_OPPORTUNITY_VIEW),
        ("work", PermissionKey.DASHBOARD_WORK_VIEW),
        ("overview", PermissionKey.DASHBOARD_OVERVIEW_VIEW),
    )
    return [
        page
        for page, permission in page_permissions
        if permission_service.has_permission(db, actor, permission)
    ]


def _business_users(db: Session) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(
                User.is_active.is_(True),
                User.role.in_(BUSINESS_USER_ROLES),
            )
            .order_by(User.display_name)
        ).all()
    )


def _scope_users_with_depths(
    db: Session,
    actor: User,
) -> list[tuple[User, int]]:
    """Return the actor's active organization subtree in hierarchy order.

    The ordinary member dashboard historically shows all business users, so
    that behavior remains unchanged. Team leaders and system administrators,
    however, are scoped to themselves and every recursive report. Traversing
    inactive users without including them keeps active descendants reachable
    when an old organization chain has not yet been reassigned.
    """
    if actor.role not in {
        UserRole.TEAM_LEADER.value,
        UserRole.SYSTEM_ADMIN.value,
    }:
        return [(user, 0) for user in _business_users(db)]

    organization_users = list(
        db.scalars(
            select(User).where(User.role != UserRole.SUPER_ADMIN.value)
        ).all()
    )
    reports_by_leader: dict[str, list[User]] = defaultdict(list)
    for user in organization_users:
        if user.leader_id:
            reports_by_leader[user.leader_id].append(user)
    for reports in reports_by_leader.values():
        reports.sort(key=lambda user: (user.display_name, user.id))

    scoped: list[tuple[User, int]] = []
    pending: deque[tuple[User, int]] = deque([(actor, 0)])
    visited: set[str] = set()
    while pending:
        user, depth = pending.popleft()
        if user.id in visited:
            continue
        visited.add(user.id)
        if user.is_active:
            scoped.append((user, depth))
        pending.extend(
            (report, depth + 1)
            for report in reports_by_leader.get(user.id, [])
            if report.id not in visited
        )

    return sorted(
        scoped,
        key=lambda item: (item[1], item[0].display_name, item[0].id),
    )


def _scope_users(db: Session, actor: User) -> list[User]:
    return [user for user, _depth in _scope_users_with_depths(db, actor)]


def _week_datetimes(week_start: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(week_start, time.min, tzinfo=SHANGHAI)
    local_end = local_start + timedelta(days=7)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def _reports_for_week(
    db: Session,
    week_start: date,
    user_ids: set[str],
) -> list[WeeklyReport]:
    if not user_ids:
        return []
    return list(
        db.scalars(
            select(WeeklyReport).where(
                WeeklyReport.week_start == week_start,
                WeeklyReport.author_id.in_(user_ids),
                WeeklyReport.submitted_content.is_not(None),
                WeeklyReport.submitted_at.is_not(None),
            )
        ).all()
    )


def _management_reports(db, week, member_ids, resolved):
    reports = _reports_for_week(db, week, member_ids)
    if resolved.is_org_wide or resolved.scope_type == SCOPE_OTHER_DIRECT:
        return reports
    departments = (
        {resolved.department_id}
        if resolved.scope_type == SCOPE_DEPARTMENT
        else {department.id for department in resolved.led_departments}
    )
    return [report for report in reports if report.department_id in departments]


def _default_attention(tasks: list[Task]) -> str:
    if any(task.status == TaskStatus.BLOCKED.value for task in tasks):
        return AttentionStatus.COORDINATE.value
    if any(
        task.priority == TaskPriority.P0.value
        and task.status not in {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}
        for task in tasks
    ):
        return AttentionStatus.FOCUS.value
    return AttentionStatus.STEADY.value


def _default_progress(project: Project, tasks: list[Task]) -> tuple[str, str, int]:
    stage = DEFAULT_STAGE_BY_PROJECT_STATUS.get(
        project.status,
        BusinessStage.LEAD.value,
    )
    base_progress = STAGE_BASE_PROGRESS[stage]
    effective_tasks = [
        task for task in tasks if task.status != TaskStatus.CANCELLED.value
    ]
    task_progress = (
        round(
            sum(task.status == TaskStatus.DONE.value for task in effective_tasks)
            / len(effective_tasks)
            * 100
        )
        if effective_tasks
        else 0
    )
    progress = 100 if stage == BusinessStage.WON.value else max(
        base_progress,
        min(task_progress, 95),
    )
    return stage, _default_attention(tasks), progress


def _changed_stage_events(
    events: list[ProjectProgress] | list[OpportunityProgress],
) -> list[ProjectProgress] | list[OpportunityProgress]:
    last_stage = BusinessStage.LEAD.value
    changed: list[ProjectProgress] = []
    for event in events:
        if event.business_stage != last_stage:
            changed.append(event)
            last_stage = event.business_stage
    return changed


def _stage_advanced(
    events: list[ProjectProgress] | list[OpportunityProgress],
    week_start: date,
) -> bool:
    before = [event for event in events if event.week_start < week_start]
    through_week = [event for event in events if event.week_start <= week_start]
    previous_stage = (
        before[-1].business_stage
        if before
        else BusinessStage.LEAD.value
    )
    current_stage = through_week[-1].business_stage if through_week else previous_stage
    return STAGE_ORDER.index(current_stage) > STAGE_ORDER.index(previous_stage)


def _project_type_labels(
    db: Session,
    project_ids: list[str],
) -> dict[str, str]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(ProjectTagAssignment.project_id, ProjectTag.name, ProjectTag.sort_order)
        .join(ProjectTag, ProjectTag.id == ProjectTagAssignment.tag_id)
        .where(
            ProjectTagAssignment.project_id.in_(project_ids),
            ProjectTag.deleted_at.is_(None),
            ProjectTag.is_active.is_(True),
        )
        .order_by(ProjectTagAssignment.project_id, ProjectTag.sort_order, ProjectTag.name)
    ).all()
    result: dict[str, str] = {}
    for project_id, name, _sort_order in rows:
        result.setdefault(project_id, name)
    return result


def _dashboard_projects(
    db: Session,
    *,
    actor: User,
    week_start: date,
    submitted_reports: list[WeeklyReport],
    visible_author_ids: set[str],
) -> tuple[
    list[DashboardProjectOut],
    list[DashboardDeliverableOut],
    list[DashboardTaskLinkOut],
    list[DashboardTimelineEventOut],
    int,
]:
    week_end = week_start + timedelta(days=6)
    projects = list(
        db.scalars(
            select(Project)
            .where(
                Project.deleted_at.is_(None),
                Project.status.in_(TRACKED_PROJECT_STATUSES),
            )
            .order_by(Project.updated_at.desc(), Project.name)
        ).all()
    )
    if not projects:
        return [], [], [], [], 0

    project_ids = [project.id for project in projects]
    project_by_id = {project.id: project for project in projects}
    user_rows = list(
        db.scalars(select(User).where(User.is_active.is_(True))).all()
    )
    users = {user.id: user for user in user_rows}
    type_labels = _project_type_labels(db, project_ids)

    tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.project_id.in_(project_ids),
                Task.deleted_at.is_(None),
            )
            .order_by(Task.created_at, Task.title)
        ).all()
    )
    tasks_by_project: dict[str, list[Task]] = defaultdict(list)
    task_by_id: dict[str, Task] = {}
    for task in tasks:
        tasks_by_project[task.project_id].append(task)
        task_by_id[task.id] = task

    collaborator_rows = db.execute(
        select(TaskCollaborator.task_id, TaskCollaborator.user_id).where(
            TaskCollaborator.task_id.in_(list(task_by_id))
        )
    ).all()
    collaborator_ids_by_task: dict[str, list[str]] = defaultdict(list)
    for task_id, user_id in collaborator_rows:
        collaborator_ids_by_task[task_id].append(user_id)

    membership_rows = db.execute(
        select(ProjectMember.project_id, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id.in_(project_ids),
            ProjectMember.left_at.is_(None),
            User.is_active.is_(True),
        )
        .order_by(ProjectMember.joined_at)
    ).all()
    people_by_project: dict[str, dict[str, User]] = defaultdict(dict)
    for project_id, user in membership_rows:
        people_by_project[project_id][user.id] = user
    for project in projects:
        if owner := users.get(project.owner_id):
            people_by_project[project.id][owner.id] = owner
        for task in tasks_by_project[project.id]:
            if owner := users.get(task.owner_id):
                people_by_project[project.id][owner.id] = owner
            for collaborator_id in collaborator_ids_by_task[task.id]:
                if collaborator := users.get(collaborator_id):
                    people_by_project[project.id][collaborator.id] = collaborator

    all_progress = list(
        db.scalars(
            select(ProjectProgress)
            .where(
                ProjectProgress.project_id.in_(project_ids),
                ProjectProgress.week_start <= week_start,
            )
            .order_by(
                ProjectProgress.project_id,
                ProjectProgress.week_start,
                ProjectProgress.created_at,
            )
        ).all()
    )
    progress_by_project: dict[str, list[ProjectProgress]] = defaultdict(list)
    for progress in all_progress:
        progress_by_project[progress.project_id].append(progress)

    work_records = list(
        db.scalars(
            select(WorkRecord)
            .where(
                WorkRecord.project_id.in_(project_ids),
                WorkRecord.work_date >= week_start,
                WorkRecord.work_date <= week_end,
                WorkRecord.deleted_at.is_(None),
            )
            .order_by(WorkRecord.work_date, WorkRecord.created_at)
        ).all()
    )
    records_by_project: dict[str, list[WorkRecord]] = defaultdict(list)
    for record in work_records:
        if record.project_id:
            records_by_project[record.project_id].append(record)

    start_at, end_at = _week_datetimes(week_start)
    deliverable_rows = db.execute(
        select(Deliverable, WorkRecord)
        .outerjoin(WorkRecord, WorkRecord.id == Deliverable.work_record_id)
        .where(
            Deliverable.project_id.in_(project_ids),
            Deliverable.deleted_at.is_(None),
            or_(
                and_(
                    WorkRecord.id.is_not(None),
                    WorkRecord.deleted_at.is_(None),
                    WorkRecord.work_date.between(week_start, week_end),
                ),
                and_(
                    Deliverable.work_record_id.is_(None),
                    Deliverable.created_at >= start_at,
                    Deliverable.created_at < end_at,
                ),
            ),
        )
        .order_by(Deliverable.created_at)
    ).all()
    deliverables_by_project: dict[str, list[Deliverable]] = defaultdict(list)
    dashboard_deliverables: list[DashboardDeliverableOut] = []
    for deliverable, source_record in deliverable_rows:
        if source_record and source_record.author_id not in visible_author_ids:
            continue
        if (
            source_record is None
            and not is_super_admin(actor)
            and deliverable.created_by not in visible_author_ids
        ):
            continue
        deliverables_by_project[deliverable.project_id].append(deliverable)
        author_id = (
            source_record.author_id if source_record else deliverable.created_by
        )
        author = users.get(author_id)
        dashboard_deliverables.append(
            DashboardDeliverableOut(
                id=deliverable.id,
                name=deliverable.name,
                url=deliverable.url,
                project_id=deliverable.project_id,
                project_name=project_by_id[deliverable.project_id].name,
                author_id=author_id,
                author_display_name=author.display_name if author else None,
            )
        )

    result_projects: list[DashboardProjectOut] = []
    timeline: list[DashboardTimelineEventOut] = []
    stage_advanced_count = 0
    trend_floor = week_start - timedelta(weeks=4)
    for project in projects:
        project_tasks = tasks_by_project[project.id]
        project_events = progress_by_project[project.id]
        latest = project_events[-1] if project_events else None
        if latest:
            business_stage = latest.business_stage
            attention_status = latest.attention_status
            progress_percent = latest.progress_percent
        else:
            business_stage, attention_status, progress_percent = _default_progress(
                project,
                project_tasks,
            )
        if _stage_advanced(project_events, week_start):
            stage_advanced_count += 1

        week_events = [
            event for event in project_events if event.week_start == week_start
        ]
        project_records = records_by_project[project.id]
        visible_records = [
            record
            for record in project_records
            if record.author_id in visible_author_ids
        ]
        event_summaries = [
            event.summary.strip() for event in week_events if event.summary.strip()
        ]
        work_summaries = [
            record.content.strip()
            for record in visible_records
            if record.content.strip()
        ]
        output_summaries = [
            event.output_summary.strip()
            for event in week_events
            if event.output_summary and event.output_summary.strip()
        ]
        output_summaries.extend(
            deliverable.name for deliverable in deliverables_by_project[project.id]
        )
        task_payload = []
        for task in project_tasks:
            owner = users.get(task.owner_id)
            task_payload.append(
                DashboardTaskOut(
                    id=task.id,
                    title=task.title,
                    status=task.status,
                    priority=task.priority,
                    owner_id=task.owner_id,
                    owner_display_name=owner.display_name if owner else "未知用户",
                    owner_avatar_key=owner.avatar_key if owner else None,
                    due_date=task.due_date,
                    blocker_reason=task.blocker_reason,
                    result=task.result,
                )
            )
        people = [
            DashboardProjectMemberOut(
                id=user.id,
                display_name=user.display_name,
                avatar_key=user.avatar_key,
            )
            for user in people_by_project[project.id].values()
        ]
        changed_events = _changed_stage_events(project_events)
        stage_history = [
            DashboardStageHistoryOut(
                id=event.id,
                week_start=event.week_start,
                business_stage=event.business_stage,
                progress_percent=event.progress_percent,
                created_at=event.created_at,
            )
            for event in changed_events
        ]
        for event in changed_events:
            if event.week_start < trend_floor:
                continue
            timeline.append(
                DashboardTimelineEventOut(
                    id=event.id,
                    opportunity_id=project.id,
                    opportunity_name=project.name,
                    week_start=event.week_start,
                    business_stage=event.business_stage,
                    attention_status=event.attention_status,
                    summary=event.summary,
                    created_at=event.created_at,
                )
            )
        result_projects.append(
            DashboardProjectOut(
                id=project.id,
                code=project.code,
                name=project.name,
                type_label=type_labels.get(project.id, "项目"),
                can_manage=(
                    permission_service.has_permission(
                        db,
                        actor,
                        PermissionKey.PROJECTS_EDIT,
                    )
                    and project_service.can_manage_project(actor, project)
                ),
                lifecycle_status=project.status,
                business_stage=business_stage,
                attention_status=attention_status,
                progress_percent=progress_percent,
                weekly_minutes=sum(record.minutes for record in visible_records),
                work_summary="；".join(dict.fromkeys(event_summaries or work_summaries))
                or "本周暂无进展记录",
                output_summary="、".join(dict.fromkeys(output_summaries))
                or "本周暂无交付物记录",
                has_week_progress=bool(week_events or visible_records),
                people=people,
                tasks=task_payload,
                work_items=[
                    DashboardWorkItemOut(
                        id=record.id,
                        author_id=record.author_id,
                        author_display_name=(
                            users[record.author_id].display_name
                            if record.author_id in users
                            else "未知用户"
                        ),
                        author_avatar_key=(
                            users[record.author_id].avatar_key
                            if record.author_id in users
                            else None
                        ),
                        content=record.content,
                        minutes=record.minutes,
                        risk=record.risk,
                        next_action=record.next_action,
                    )
                    for record in visible_records
                ],
                stage_history=stage_history,
            )
        )

    active_task_ids = set(task_by_id)
    relation_rows = list(
        db.scalars(
            select(TaskRelation)
            .where(
                TaskRelation.deleted_at.is_(None),
                TaskRelation.source_task_id.in_(active_task_ids),
                TaskRelation.target_task_id.in_(active_task_ids),
            )
            .order_by(TaskRelation.created_at)
        ).all()
    )
    task_links = [
        DashboardTaskLinkOut(
            id=relation.id,
            source_task_id=relation.source_task_id,
            target_task_id=relation.target_task_id,
            label=relation.label,
        )
        for relation in relation_rows
    ]
    timeline.sort(key=lambda item: (item.week_start, item.created_at), reverse=True)
    return (
        result_projects,
        dashboard_deliverables,
        task_links,
        timeline,
        stage_advanced_count,
    )


def _dashboard_opportunities(
    db: Session,
    *,
    actor: User,
    week_start: date,
) -> tuple[
    list[DashboardOpportunityOut],
    list[DashboardTimelineEventOut],
    int,
]:
    opportunities = list(
        db.scalars(
            select(Opportunity)
            .where(
                Opportunity.deleted_at.is_(None),
                Opportunity.status.in_(TRACKED_OPPORTUNITY_STATUSES),
            )
            .order_by(Opportunity.updated_at.desc(), Opportunity.name)
        ).all()
    )
    if not opportunities:
        return [], [], 0

    opportunity_ids = [opportunity.id for opportunity in opportunities]
    user_rows = list(db.scalars(select(User).where(User.is_active.is_(True))).all())
    users = {user.id: user for user in user_rows}
    membership_rows = db.execute(
        select(OpportunityMember.opportunity_id, OpportunityMember.user_id)
        .where(OpportunityMember.opportunity_id.in_(opportunity_ids))
        .order_by(OpportunityMember.added_at)
    ).all()
    member_ids_by_opportunity: dict[str, list[str]] = defaultdict(list)
    for opportunity_id, user_id in membership_rows:
        member_ids_by_opportunity[opportunity_id].append(user_id)

    progress_rows = list(
        db.scalars(
            select(OpportunityProgress)
            .where(
                OpportunityProgress.opportunity_id.in_(opportunity_ids),
                OpportunityProgress.week_start <= week_start,
            )
            .order_by(
                OpportunityProgress.opportunity_id,
                OpportunityProgress.week_start,
                OpportunityProgress.created_at,
            )
        ).all()
    )
    progress_by_opportunity: dict[str, list[OpportunityProgress]] = defaultdict(list)
    for progress in progress_rows:
        progress_by_opportunity[progress.opportunity_id].append(progress)

    linked_project_ids = {
        opportunity.linked_project_id
        for opportunity in opportunities
        if opportunity.linked_project_id
    }
    linked_projects = {
        project.id: project
        for project in db.scalars(
            select(Project).where(Project.id.in_(linked_project_ids))
        ).all()
    } if linked_project_ids else {}

    can_record_progress = permission_service.has_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS,
    )
    can_create_project = permission_service.has_permission(
        db,
        actor,
        PermissionKey.PROJECTS_CREATE,
    )
    timeline: list[DashboardTimelineEventOut] = []
    result: list[DashboardOpportunityOut] = []
    stage_advanced_count = 0
    trend_floor = week_start - timedelta(weeks=4)
    for opportunity in opportunities:
        events = progress_by_opportunity[opportunity.id]
        latest = events[-1] if events else None
        business_stage = (
            latest.business_stage if latest else opportunity.business_stage
        )
        attention_status = (
            latest.attention_status if latest else opportunity.attention_status
        )
        progress_percent = (
            latest.progress_percent if latest else opportunity.progress_percent
        )
        if _stage_advanced(events, week_start):
            stage_advanced_count += 1
        week_events = [event for event in events if event.week_start == week_start]
        changed_events = _changed_stage_events(events)
        for event in changed_events:
            if event.week_start < trend_floor:
                continue
            timeline.append(
                DashboardTimelineEventOut(
                    id=event.id,
                    opportunity_id=opportunity.id,
                    opportunity_name=opportunity.name,
                    week_start=event.week_start,
                    business_stage=event.business_stage,
                    attention_status=event.attention_status,
                    summary=event.summary,
                    created_at=event.created_at,
                )
            )
        owner = users.get(opportunity.owner_id)
        people_ids = list(
            dict.fromkeys(
                [opportunity.owner_id, *member_ids_by_opportunity[opportunity.id]]
            )
        )
        linked_project = linked_projects.get(opportunity.linked_project_id or "")
        can_manage = can_record_progress and opportunity_service.can_manage_opportunity(
            actor,
            opportunity,
        )
        result.append(
            DashboardOpportunityOut(
                id=opportunity.id,
                code=opportunity.code,
                name=opportunity.name,
                customer_name=opportunity.customer_name,
                description=opportunity.description,
                owner_id=opportunity.owner_id,
                owner_display_name=owner.display_name if owner else "未知用户",
                owner_avatar_key=owner.avatar_key if owner else None,
                can_manage=can_manage,
                can_convert=(
                    can_manage
                    and can_create_project
                    and opportunity_service.can_convert_opportunity(
                        actor,
                        opportunity,
                    )
                ),
                status=opportunity.status,
                business_stage=business_stage,
                attention_status=attention_status,
                progress_percent=progress_percent,
                work_summary="；".join(
                    dict.fromkeys(
                        event.summary.strip()
                        for event in week_events
                        if event.summary.strip()
                    )
                )
                or "本周暂无商机进展",
                output_summary="；".join(
                    dict.fromkeys(
                        event.output_summary.strip()
                        for event in week_events
                        if event.output_summary and event.output_summary.strip()
                    )
                )
                or "本周暂无商机输出",
                has_week_progress=bool(week_events),
                linked_project_id=(linked_project.id if linked_project else None),
                linked_project_code=(linked_project.code if linked_project else None),
                linked_project_name=(linked_project.name if linked_project else None),
                linked_project_status=(
                    linked_project.status if linked_project else None
                ),
                people=[
                    DashboardProjectMemberOut(
                        id=user_id,
                        display_name=users[user_id].display_name,
                        avatar_key=users[user_id].avatar_key,
                    )
                    for user_id in people_ids
                    if user_id in users
                ],
                stage_history=[
                    DashboardStageHistoryOut(
                        id=event.id,
                        week_start=event.week_start,
                        business_stage=event.business_stage,
                        progress_percent=event.progress_percent,
                        created_at=event.created_at,
                    )
                    for event in changed_events
                ],
                revision=opportunity.revision,
            )
        )

    timeline.sort(key=lambda item: (item.week_start, item.created_at), reverse=True)
    return result, timeline, stage_advanced_count


def _week_trends(
    db: Session,
    weeks: list[date],
    member_ids: set[str],
    work_author_ids: set[str],
    period_scopes: dict,
) -> list[DashboardWeekTrendOut]:
    trends: list[DashboardWeekTrendOut] = []
    for week_start in weeks:
        period = period_scopes[week_start]
        period_member_ids = member_ids if period.is_org_wide else {u.id for u in period.members}
        period_author_ids = work_author_ids if period.is_org_wide else period_member_ids
        week_end = week_start + timedelta(days=6)
        total_minutes = (
            db.scalar(
                select(func.sum(WorkRecord.minutes)).where(
                    WorkRecord.author_id.in_(period_author_ids),
                    WorkRecord.work_date >= week_start,
                    WorkRecord.work_date <= week_end,
                    WorkRecord.deleted_at.is_(None),
                )
            )
            or 0
        )
        deliverable_count = (
            db.scalar(
                select(func.count(Deliverable.id))
                .join(WorkRecord, WorkRecord.id == Deliverable.work_record_id)
                .where(
                    WorkRecord.author_id.in_(period_author_ids),
                    WorkRecord.work_date >= week_start,
                    WorkRecord.work_date <= week_end,
                    WorkRecord.deleted_at.is_(None),
                    Deliverable.deleted_at.is_(None),
                )
            )
            or 0
        )
        submitted_count = len(_management_reports(db, week_start, period_member_ids, period))
        trends.append(
            DashboardWeekTrendOut(
                week_start=week_start,
                week_end=week_end,
                total_minutes=total_minutes,
                deliverable_count=deliverable_count,
                submitted_count=submitted_count,
                member_count=len(period_member_ids),
                member_count_known=period.roster_known,
            )
        )
    return trends


def build_dashboard(
    db: Session,
    actor: User,
    *,
    selected_week_start: date | None = None,
    scope_type: str | None = None,
    department_id: str | None = None,
) -> DashboardOut:
    pages = accessible_pages(db, actor)
    if not pages:
        raise PermissionDeniedError("当前账号没有可见的作战台视图")
    can_view_opportunity = "opp" in pages
    can_view_work = "work" in pages
    can_view_overview = "overview" in pages
    current_week = normalize_week_start()
    selected_week = normalize_week_start(selected_week_start)
    # 周列表始终锚定当前周：否则选中历史周后，下拉选项会随选中周漂移，
    # 导致用户无法直接切回当前周。
    weeks = [current_week - timedelta(weeks=index) for index in range(4, -1, -1)]
    resolved = resolve_management_scope(
        db,
        actor,
        scope_type=scope_type if can_view_work or can_view_overview else None,
        department_id=department_id if can_view_work or can_view_overview else None,
        week_start=selected_week,
    )
    scope_users = _scope_users(db, actor) if resolved.is_org_wide else list(resolved.members)
    member_ids = {user.id for user in scope_users}
    # 工作贡献统计：管理范围内成员；超管全量；普通成员仅自己。
    if is_super_admin(actor):
        visible_author_ids = {user.id for user in _business_users(db)} | {actor.id}
    elif not resolved.is_org_wide and actor.role in {
        UserRole.TEAM_LEADER.value,
        UserRole.SYSTEM_ADMIN.value,
    }:
        visible_author_ids = member_ids | {actor.id}
    else:
        visible_author_ids = {actor.id}
    work_author_ids = visible_author_ids
    submissions = _management_reports(db, selected_week, member_ids, resolved)
    submission_by_author = {report.author_id: report for report in submissions}
    submitted_weeks_by_author: dict[str, list[date]] = defaultdict(list)
    eligible_weeks_by_author: dict[str, list[date]] = defaultdict(list)
    period_scopes = {}
    for week in weeks:
        period = (
            resolved
            if week == selected_week
            else resolve_management_scope(
                db,
                actor,
                scope_type=scope_type,
                department_id=department_id,
                week_start=week,
            )
        )
        period_scopes[week] = period
        ids = member_ids if period.is_org_wide else {user.id for user in period.members}
        for report in _management_reports(db, week, ids, period):
            submitted_weeks_by_author[report.author_id].append(week)
        if period.roster_known:
            for uid in ids:
                eligible_weeks_by_author[uid].append(week)

    weekly_minutes_rows = db.execute(
        select(WorkRecord.author_id, func.sum(WorkRecord.minutes))
        .where(
            WorkRecord.author_id.in_(work_author_ids),
            WorkRecord.work_date >= selected_week,
            WorkRecord.work_date <= selected_week + timedelta(days=6),
            WorkRecord.deleted_at.is_(None),
        )
        .group_by(WorkRecord.author_id)
    ).all()
    weekly_minutes = {author_id: int(minutes) for author_id, minutes in weekly_minutes_rows}
    department_names = {department.id: department.name for department in resolved.led_departments}
    members = [
        DashboardMemberOut(
            id=user.id,
            display_name=user.display_name,
            role=user.role,
            avatar_key=user.avatar_key,
            submitted=user.id in submission_by_author,
            submitted_at=(
                submission_by_author[user.id].submitted_at
                if user.id in submission_by_author
                else None
            ),
            weekly_minutes=(
                weekly_minutes.get(user.id, 0)
                if can_view_work
                and (is_super_admin(actor) or user.id == actor.id or user.id in member_ids)
                else None
            ),
            submitted_weeks=submitted_weeks_by_author[user.id],
            eligible_weeks=eligible_weeks_by_author[user.id],
            department_id=resolved.department_by_user.get(user.id, user.primary_department_id),
            department_name=(
                department_names.get(
                    resolved.department_by_user.get(user.id, user.primary_department_id)
                )
            ),
        )
        for user in scope_users
    ]

    (
        projects,
        deliverables,
        task_links,
        _project_stage_timeline,
        _project_stage_advanced_count,
    ) = _dashboard_projects(
        db,
        actor=actor,
        week_start=selected_week,
        submitted_reports=submissions,
        visible_author_ids=visible_author_ids,
    )
    opportunities, stage_timeline, stage_advanced_count = _dashboard_opportunities(
        db,
        actor=actor,
        week_start=selected_week,
    )
    stage_distribution = [
        DashboardStageCountOut(
            business_stage=stage,
            count=sum(opportunity.business_stage == stage for opportunity in opportunities),
        )
        for stage in STAGE_ORDER
    ]
    total_minutes = sum(project.weekly_minutes for project in projects)
    resolved_scope_key = (
        "all_led"
        if resolved.is_org_wide
        else normalize_scope_key(resolved.scope_type, resolved.department_id)
    )
    latest_summary = None
    if permission_service.has_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_TEAM_SUMMARY,
    ):
        latest_summary = db.scalar(
            select(TeamWeeklySummary)
            .where(
                TeamWeeklySummary.week_start == selected_week,
                TeamWeeklySummary.generated_by == actor.id,
                TeamWeeklySummary.scope_key == resolved_scope_key,
            )
            .order_by(TeamWeeklySummary.created_at.desc())
            .limit(1)
        )
    project_ids = [project.id for project in projects]
    progress_summaries: dict[str, list[str]] = defaultdict(list)
    progress_outputs: dict[str, list[str]] = defaultdict(list)
    if can_view_opportunity and not can_view_work and project_ids:
        selected_progress = list(
            db.scalars(
                select(ProjectProgress)
                .where(
                    ProjectProgress.project_id.in_(project_ids),
                    ProjectProgress.week_start == selected_week,
                )
                .order_by(ProjectProgress.created_at)
            ).all()
        )
        for progress in selected_progress:
            if progress.summary.strip():
                progress_summaries[progress.project_id].append(progress.summary.strip())
            if progress.output_summary and progress.output_summary.strip():
                progress_outputs[progress.project_id].append(progress.output_summary.strip())

    deliverable_names: dict[str, list[str]] = defaultdict(list)
    if can_view_work and not can_view_opportunity:
        for deliverable in deliverables:
            deliverable_names[deliverable.project_id].append(deliverable.name)

    projects_for_response = []
    if can_view_opportunity or can_view_work:
        for project in projects:
            updates: dict[str, object] = {}
            if not can_view_opportunity:
                work_summaries = [
                    item.content.strip() for item in project.work_items if item.content.strip()
                ]
                updates.update(
                    can_manage=False,
                    business_stage=BusinessStage.LEAD.value,
                    attention_status=AttentionStatus.STEADY.value,
                    progress_percent=0,
                    work_summary="；".join(dict.fromkeys(work_summaries)) or "本周暂无工作记录",
                    output_summary="；".join(dict.fromkeys(deliverable_names[project.id]))
                    or "本周暂无交付物记录",
                    has_week_progress=bool(project.work_items or deliverable_names[project.id]),
                    tasks=[],
                    stage_history=[],
                )
            if not can_view_work:
                safe_summaries = progress_summaries[project.id]
                safe_outputs = progress_outputs[project.id]
                updates.update(
                    weekly_minutes=None,
                    work_summary="；".join(dict.fromkeys(safe_summaries)) or "本周暂无项目进展记录",
                    output_summary="；".join(dict.fromkeys(safe_outputs)) or "本周暂无项目进展产出",
                    has_week_progress=bool(safe_summaries or safe_outputs),
                    work_items=[],
                )
            projects_for_response.append(project.model_copy(update=updates))
    trends = (
        _week_trends(db, weeks, member_ids, work_author_ids, period_scopes)
        if can_view_overview
        else []
    )
    return DashboardOut(
        accessible_pages=pages,
        selected_week=week_out(selected_week, current_week=current_week),
        weeks=[week_out(item, current_week=current_week) for item in weeks],
        metrics=DashboardMetricsOut(
            tracking_count=(len(opportunities) if can_view_opportunity or can_view_overview else 0),
            focus_count=(
                sum(
                    opportunity.attention_status == AttentionStatus.FOCUS.value
                    for opportunity in opportunities
                )
                if can_view_opportunity
                else 0
            ),
            stage_advanced_count=stage_advanced_count if can_view_opportunity else 0,
            deliverable_count=len(deliverables) if can_view_work else 0,
            coordinate_count=(
                sum(
                    opportunity.attention_status == AttentionStatus.COORDINATE.value
                    for opportunity in opportunities
                )
                if can_view_opportunity or can_view_overview
                else 0
            ),
            total_minutes=total_minutes if can_view_work else 0,
            submitted_count=len(submissions) if can_view_work else 0,
            member_count=len(members) if can_view_work else 0,
            member_count_known=resolved.roster_known,
        ),
        members=members if can_view_work or can_view_overview else [],
        opportunities=opportunities if can_view_opportunity else [],
        projects=projects_for_response,
        deliverables=deliverables if can_view_work else [],
        task_links=task_links if can_view_opportunity else [],
        trends=trends,
        stage_distribution=(
            stage_distribution if can_view_opportunity or can_view_overview else []
        ),
        stage_timeline=(stage_timeline if can_view_opportunity or can_view_overview else []),
        latest_team_summary=(
            TeamWeeklySummaryOut.model_validate(latest_summary)
            if latest_summary and can_view_work
            else None
        ),
        management_scope=(
            ManagementScopeOut(
                scope_type=resolved.scope_type,
                department_id=resolved.department_id,
                options=[
                    ManagementScopeOptionOut(
                        scope_type=option.scope_type,
                        department_id=option.department_id,
                        department_name=option.department_name,
                        member_count=option.member_count,
                    )
                    for option in resolved.options
                ],
                other_direct_count=resolved.other_direct_count,
            )
            if (can_view_work or can_view_overview)
            and not resolved.is_org_wide
            and resolved.options
            else None
        ),
    )


def record_project_progress(
    db: Session,
    project: Project,
    payload: ProjectProgressCreate,
    actor: User,
) -> ProjectProgress:
    project_service.require_manage_project(actor, project)
    progress = ProjectProgress(
        project_id=project.id,
        week_start=payload.week_start,
        business_stage=payload.business_stage.value,
        attention_status=payload.attention_status.value,
        progress_percent=payload.progress_percent,
        summary=payload.summary.strip(),
        output_summary=(
            payload.output_summary.strip() if payload.output_summary else None
        ),
        created_by=actor.id,
    )
    db.add(progress)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="project.progress.record",
        entity_type="project_progress",
        entity_id=progress.id,
        after_data=ProjectProgressOut.model_validate(progress).model_dump(
            mode="json"
        ),
        detail={"projectId": project.id},
    )
    return progress


def create_task_relation(
    db: Session,
    payload: TaskRelationCreate,
    actor: User,
) -> TaskRelation:
    source = task_service.get_task(db, payload.source_task_id, actor=actor)
    target = task_service.get_task(db, payload.target_task_id, actor=actor)
    if source.id == target.id:
        raise AppError("TASK_RELATION_SELF", "不能将任务关联到自身")
    if not source.project_id or not target.project_id:
        raise AppError(
            "TASK_RELATION_PROJECT_REQUIRED",
            "跨项目任务关联仅支持项目来源的任务",
        )
    if source.project_id == target.project_id:
        raise AppError("TASK_RELATION_SAME_PROJECT", "跨项目关联必须连接不同项目的任务")
    source_project = project_service.get_project(db, source.project_id)
    target_project = project_service.get_project(db, target.project_id)
    if not (
        project_service.can_manage_project(actor, source_project)
        and project_service.can_manage_project(actor, target_project)
    ):
        raise PermissionDeniedError("只有两个项目的负责人或管理角色可以建立任务关联")
    source_id, target_id = sorted((source.id, target.id))
    existing = db.scalar(
        select(TaskRelation).where(
            TaskRelation.source_task_id == source_id,
            TaskRelation.target_task_id == target_id,
            TaskRelation.deleted_at.is_(None),
        )
    )
    if existing:
        raise ConflictError(
            "TASK_RELATION_EXISTS",
            "这两个任务已经建立关联",
            {"relation_id": existing.id},
        )
    relation = TaskRelation(
        source_task_id=source_id,
        target_task_id=target_id,
        label=payload.label.strip(),
        created_by=actor.id,
    )
    db.add(relation)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="task.relation.create",
        entity_type="task_relation",
        entity_id=relation.id,
        after_data=TaskRelationOut.model_validate(relation).model_dump(mode="json"),
    )
    return relation


def generate_team_summary(
    db: Session,
    settings: Settings,
    payload: TeamWeeklySummaryGenerate,
    actor: User,
    *,
    week_start: date,
    llm_guard: LLMGuard,
) -> TeamWeeklySummary:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_TEAM_SUMMARY,
        "当前账号没有生成团队周报的权限",
    )
    normalized_week = normalize_week_start(week_start)
    resolved = resolve_management_scope(
        db,
        actor,
        scope_type=payload.scope_type,
        department_id=payload.department_id,
        week_start=normalized_week,
    )
    if resolved.is_org_wide:
        scoped_users_with_depths = _scope_users_with_depths(db, actor)
        scope_users = [user for user, _depth in scoped_users_with_depths]
        depth_by_user_id = {user.id: depth for user, depth in scoped_users_with_depths}
    else:
        # 管理范围不含负责人本人。
        tree_with_depths = {user.id: depth for user, depth in _scope_users_with_depths(db, actor)}
        scope_users = [user for user in resolved.members if user.id != actor.id]
        depth_by_user_id = {user.id: tree_with_depths.get(user.id, 0) for user in scope_users}
    member_ids = {user.id for user in scope_users}
    reports = _management_reports(db, normalized_week, member_ids, resolved)
    submitted_ids = {report.author_id for report in reports}
    missing = [user.display_name for user in scope_users if user.id not in submitted_ids]
    if not resolved.roster_known and not payload.force:
        raise ConflictError(
            "HISTORICAL_ROSTER_UNKNOWN", "历史应提交人数未知，请选择按已提交内容直接生成"
        )
    if missing and not payload.force:
        raise ConflictError(
            "TEAM_WEEKLY_REPORTS_INCOMPLETE",
            "仍有成员未提交周报，请等待全员提交或选择直接生成",
            {
                "missing_members": missing,
                "submitted_count": len(reports),
                "expected_count": len(scope_users),
            },
        )
    if not reports:
        raise AppError("TEAM_WEEKLY_REPORTS_EMPTY", "本周还没有可汇总的已提交周报")

    users = {user.id: user for user in scope_users}
    ordered_reports = sorted(
        reports,
        key=lambda report: (
            depth_by_user_id.get(report.author_id, 0),
            {
                UserRole.SYSTEM_ADMIN.value: 0,
                UserRole.TEAM_LEADER.value: 1,
                UserRole.MEMBER.value: 2,
            }.get(users[report.author_id].role, 3),
            users[report.author_id].display_name,
            report.author_id,
        ),
    )
    department_names = {d.id: d.name for d in resolved.led_departments}
    report_context = "\n\n".join(
        (
            f"## {users[report.author_id].display_name}\n"
            f"部门：{department_names.get(report.department_id, '历史部门归属未知')}\n"
            f"{report.submitted_content or ''}"
        )
        for report in ordered_reports
    )
    included_leader_count = sum(
        users[report.author_id].role in {UserRole.TEAM_LEADER.value, UserRole.SYSTEM_ADMIN.value}
        for report in ordered_reports
    )
    source_reports = [
        {
            "report_id": report.id,
            "author_id": report.author_id,
            "submission_version": report.submission_version,
            "department_id": report.department_id,
            "order": order,
            "depth": depth_by_user_id.get(report.author_id, 0),
        }
        for order, report in enumerate(ordered_reports, start=1)
    ]
    missing_text = (
        ("、".join(missing) if missing else "无")
        if resolved.roster_known
        else "历史成员名单缺失，未提交成员未知"
    )
    expected_text = (
        str(len(scope_users)) + " 位"
        if resolved.roster_known
        else "未知，禁止计算提交率或声称全员提交"
    )
    scope_key = (
        "all_led"
        if resolved.is_org_wide
        else normalize_scope_key(resolved.scope_type, resolved.department_id)
    )
    scope_title = "解决方案部门"
    if not resolved.is_org_wide:
        if resolved.scope_type == SCOPE_DEPARTMENT and resolved.department_id:
            department = next(
                (item for item in resolved.led_departments if item.id == resolved.department_id),
                None,
            )
            scope_title = department.name if department else "分管部门"
        elif resolved.scope_type == SCOPE_OTHER_DIRECT:
            scope_title = "其他直属成员"
        else:
            scope_title = "全部分管部门"
    with llm_guard.generation(
        user_id=actor.id,
        purpose="team_summary",
        max_tokens=6144,
        idempotency_key=(f"team-summary:{actor.id}:{normalized_week.isoformat()}:{scope_key}"),
    ) as lease:
        result = ai_service.complete(
            db,
            settings,
            messages=[
                {"role": "system", "content": TEAM_SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "system",
                    "content": (
                        f"汇总范围：{scope_title}\n"
                        "跨部门汇总必须按已知部门分章节；未知归属单列，不得推断。\n"
                        f"统计周：{normalized_week.isoformat()} 至 "
                        f"{(normalized_week + timedelta(days=6)).isoformat()}\n"
                        f"应提交成员：{expected_text}\n"
                        f"实际提交成员：{len(reports)} 位\n"
                        f"未提交成员：{missing_text}\n\n"
                        f"以下为已提交个人周报：\n{report_context}"
                    ),
                },
                {
                    "role": "user",
                    "content": TEAM_SUMMARY_USER_PROMPT.replace(
                        "# 解决方案部门周报",
                        f"# {scope_title}周报",
                    ),
                },
            ],
            max_tokens=6144,
        )
        lease.record_usage(result.usage)
    summary = db.scalar(
        select(TeamWeeklySummary).where(
            TeamWeeklySummary.generated_by == actor.id,
            TeamWeeklySummary.week_start == normalized_week,
            TeamWeeklySummary.scope_key == scope_key,
        )
    )
    is_regeneration = summary is not None
    department_id = resolved.department_id if resolved.scope_type == SCOPE_DEPARTMENT else None
    if summary is None:
        summary = TeamWeeklySummary(
            week_start=normalized_week,
            week_end=normalized_week + timedelta(days=6),
            content=result.answer,
            generated_by=actor.id,
            forced=payload.force,
            submitted_count=len(reports),
            expected_count=len(scope_users),
            expected_count_known=resolved.roster_known,
            included_leader_count=included_leader_count,
            source_reports=source_reports,
            generation_model=result.model,
            generation_usage=result.usage,
            scope_type=resolved.scope_type if not resolved.is_org_wide else SCOPE_ALL_LED,
            department_id=department_id,
            scope_key=scope_key,
        )
        db.add(summary)
    else:
        summary.content = result.answer
        summary.forced = payload.force
        summary.submitted_count = len(reports)
        summary.expected_count = len(scope_users)
        summary.expected_count_known = resolved.roster_known
        summary.included_leader_count = included_leader_count
        summary.source_reports = source_reports
        summary.generation_model = result.model
        summary.generation_usage = result.usage
        summary.scope_type = resolved.scope_type if not resolved.is_org_wide else SCOPE_ALL_LED
        summary.department_id = department_id
        summary.scope_key = scope_key
        summary.revision += 1
        summary.updated_at = datetime.now(UTC)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action=(
            "team_weekly_summary.regenerate" if is_regeneration else "team_weekly_summary.generate"
        ),
        entity_type="team_weekly_summary",
        entity_id=summary.id,
        detail={
            "weekStart": normalized_week.isoformat(),
            "forced": payload.force,
            "submittedCount": len(reports),
            "expectedCount": len(scope_users),
            "includedLeaderCount": included_leader_count,
            "scopeKey": scope_key,
            "model": result.model,
            "usage": result.usage,
        },
    )
    return summary
