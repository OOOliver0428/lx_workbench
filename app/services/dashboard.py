from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.config import Settings
from app.domain import is_super_admin
from app.errors import AppError, ConflictError, PermissionDeniedError
from app.models import (
    AttentionStatus,
    BusinessStage,
    Deliverable,
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
    ProjectProgressCreate,
    ProjectProgressOut,
    TaskRelationCreate,
    TaskRelationOut,
    TeamWeeklySummaryGenerate,
    TeamWeeklySummaryOut,
)
from app.services import ai as ai_service
from app.services import permissions as permission_service
from app.services import projects as project_service

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


def _scope_users(db: Session, actor: User) -> list[User]:
    users = _business_users(db)
    if actor.role not in {
        UserRole.TEAM_LEADER.value,
        UserRole.SYSTEM_ADMIN.value,
    }:
        return users
    direct_reports = [user for user in users if user.leader_id == actor.id]
    if not direct_reports:
        return users
    if actor.role in BUSINESS_USER_ROLES:
        direct_reports.append(actor)
    unique_users = {user.id: user for user in direct_reports}.values()
    return sorted(unique_users, key=lambda item: item.display_name)


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


def _reports_visible_to_summary(
    actor: User,
    reports: list[WeeklyReport],
) -> list[WeeklyReport]:
    if is_super_admin(actor):
        return reports
    return [
        report
        for report in reports
        if report.author_id == actor.id or report.submitted_to_id == actor.id
    ]


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
    events: list[ProjectProgress],
) -> list[ProjectProgress]:
    last_stage = BusinessStage.LEAD.value
    changed: list[ProjectProgress] = []
    for event in events:
        if event.business_stage != last_stage:
            changed.append(event)
            last_stage = event.business_stage
    return changed


def _stage_advanced(
    events: list[ProjectProgress],
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
                WorkRecord.work_date.between(week_start, week_end),
                (
                    (Deliverable.work_record_id.is_(None))
                    & (Deliverable.created_at >= start_at)
                    & (Deliverable.created_at < end_at)
                ),
            ),
        )
        .order_by(Deliverable.created_at)
    ).all()
    deliverables_by_project: dict[str, list[Deliverable]] = defaultdict(list)
    dashboard_deliverables: list[DashboardDeliverableOut] = []
    for deliverable, source_record in deliverable_rows:
        if (
            source_record
            and not is_super_admin(actor)
            and source_record.author_id != actor.id
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
        visible_records = (
            project_records
            if is_super_admin(actor)
            else [
                record
                for record in project_records
                if record.author_id == actor.id
            ]
        )
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
                    project_id=project.id,
                    project_name=project.name,
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
                        PermissionKey.PROJECTS_MANAGE,
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


def _week_trends(
    db: Session,
    weeks: list[date],
    member_ids: set[str],
    work_author_ids: set[str],
) -> list[DashboardWeekTrendOut]:
    trends: list[DashboardWeekTrendOut] = []
    for week_start in weeks:
        week_end = week_start + timedelta(days=6)
        total_minutes = (
            db.scalar(
                select(func.sum(WorkRecord.minutes)).where(
                    WorkRecord.author_id.in_(work_author_ids),
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
                    WorkRecord.author_id.in_(work_author_ids),
                    WorkRecord.work_date >= week_start,
                    WorkRecord.work_date <= week_end,
                    WorkRecord.deleted_at.is_(None),
                    Deliverable.deleted_at.is_(None),
                )
            )
            or 0
        )
        submitted_count = (
            db.scalar(
                select(func.count(WeeklyReport.id)).where(
                    WeeklyReport.author_id.in_(member_ids),
                    WeeklyReport.week_start == week_start,
                    WeeklyReport.submitted_content.is_not(None),
                    WeeklyReport.submitted_at.is_not(None),
                )
            )
            or 0
        )
        trends.append(
            DashboardWeekTrendOut(
                week_start=week_start,
                week_end=week_end,
                total_minutes=total_minutes,
                deliverable_count=deliverable_count,
                submitted_count=submitted_count,
                member_count=len(member_ids),
            )
        )
    return trends


def build_dashboard(
    db: Session,
    actor: User,
    *,
    selected_week_start: date | None = None,
) -> DashboardOut:
    pages = accessible_pages(db, actor)
    if not pages:
        raise PermissionDeniedError("当前账号没有可见的作战台视图")
    current_week = normalize_week_start()
    selected_week = normalize_week_start(selected_week_start)
    weeks = [selected_week - timedelta(weeks=index) for index in range(4, -1, -1)]
    scope_users = _scope_users(db, actor)
    member_ids = {user.id for user in scope_users}
    work_author_ids = (
        member_ids | {actor.id}
        if is_super_admin(actor)
        else {actor.id}
    )
    submissions = _reports_for_week(db, selected_week, member_ids)
    submission_by_author = {report.author_id: report for report in submissions}
    submitted_week_rows = db.execute(
        select(WeeklyReport.author_id, WeeklyReport.week_start).where(
            WeeklyReport.author_id.in_(member_ids),
            WeeklyReport.week_start.in_(weeks),
            WeeklyReport.submitted_content.is_not(None),
            WeeklyReport.submitted_at.is_not(None),
        )
    ).all()
    submitted_weeks_by_author: dict[str, list[date]] = defaultdict(list)
    for author_id, report_week_start in submitted_week_rows:
        submitted_weeks_by_author[author_id].append(report_week_start)

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
            weekly_minutes=weekly_minutes.get(user.id, 0),
            submitted_weeks=submitted_weeks_by_author[user.id],
        )
        for user in scope_users
    ]

    (
        projects,
        deliverables,
        task_links,
        stage_timeline,
        stage_advanced_count,
    ) = _dashboard_projects(
        db,
        actor=actor,
        week_start=selected_week,
        submitted_reports=submissions,
    )
    stage_distribution = [
        DashboardStageCountOut(
            business_stage=stage,
            count=sum(project.business_stage == stage for project in projects),
        )
        for stage in STAGE_ORDER
    ]
    total_minutes = sum(project.weekly_minutes for project in projects)
    latest_summary = (
        db.scalar(
            select(TeamWeeklySummary)
            .where(
                TeamWeeklySummary.week_start == selected_week,
                TeamWeeklySummary.generated_by == actor.id,
            )
            .order_by(TeamWeeklySummary.created_at.desc())
            .limit(1)
        )
        if permission_service.has_permission(
            db,
            actor,
            PermissionKey.DASHBOARD_TEAM_SUMMARY,
        )
        else None
    )
    return DashboardOut(
        accessible_pages=pages,
        selected_week=week_out(selected_week, current_week=current_week),
        weeks=[week_out(item, current_week=current_week) for item in weeks],
        metrics=DashboardMetricsOut(
            tracking_count=len(projects),
            focus_count=sum(
                project.attention_status == AttentionStatus.FOCUS.value
                for project in projects
            ),
            stage_advanced_count=stage_advanced_count,
            deliverable_count=len(deliverables),
            coordinate_count=sum(
                project.attention_status == AttentionStatus.COORDINATE.value
                for project in projects
            ),
            total_minutes=total_minutes,
            submitted_count=len(submissions),
            member_count=len(members),
        ),
        members=members,
        projects=projects,
        deliverables=deliverables,
        task_links=task_links,
        trends=_week_trends(db, weeks, member_ids, work_author_ids),
        stage_distribution=stage_distribution,
        stage_timeline=stage_timeline,
        latest_team_summary=(
            TeamWeeklySummaryOut.model_validate(latest_summary)
            if latest_summary
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
    source = db.get(Task, payload.source_task_id)
    target = db.get(Task, payload.target_task_id)
    if (
        not source
        or source.deleted_at
        or not target
        or target.deleted_at
    ):
        raise AppError("TASK_NOT_FOUND", "关联任务不存在", status_code=404)
    if source.id == target.id:
        raise AppError("TASK_RELATION_SELF", "不能将任务关联到自身")
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
) -> TeamWeeklySummary:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_TEAM_SUMMARY,
        "当前账号没有生成团队周报的权限",
    )
    normalized_week = normalize_week_start(week_start)
    scope_users = _scope_users(db, actor)
    member_ids = {user.id for user in scope_users}
    reports = _reports_visible_to_summary(
        actor,
        _reports_for_week(db, normalized_week, member_ids),
    )
    submitted_ids = {report.author_id for report in reports}
    missing = [
        user.display_name for user in scope_users if user.id not in submitted_ids
    ]
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
    report_context = "\n\n".join(
        (
            f"## {users[report.author_id].display_name}\n"
            f"{report.submitted_content or ''}"
        )
        for report in sorted(
            reports,
            key=lambda item: users[item.author_id].display_name,
        )
    )
    missing_text = "、".join(missing) if missing else "无"
    result = ai_service.complete(
        db,
        settings,
        messages=[
            {"role": "system", "content": TEAM_SUMMARY_SYSTEM_PROMPT},
            {
                "role": "system",
                "content": (
                    f"统计周：{normalized_week.isoformat()} 至 "
                    f"{(normalized_week + timedelta(days=6)).isoformat()}\n"
                    f"应提交成员：{len(scope_users)} 位\n"
                    f"实际提交成员：{len(reports)} 位\n"
                    f"未提交成员：{missing_text}\n\n"
                    f"以下为已提交个人周报：\n{report_context}"
                ),
            },
            {"role": "user", "content": TEAM_SUMMARY_USER_PROMPT},
        ],
        max_tokens=6144,
    )
    summary = TeamWeeklySummary(
        week_start=normalized_week,
        week_end=normalized_week + timedelta(days=6),
        content=result.answer,
        generated_by=actor.id,
        forced=payload.force,
        submitted_count=len(reports),
        expected_count=len(scope_users),
        generation_model=result.model,
        generation_usage=result.usage,
    )
    db.add(summary)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="team_weekly_summary.generate",
        entity_type="team_weekly_summary",
        entity_id=summary.id,
        detail={
            "weekStart": normalized_week.isoformat(),
            "forced": payload.force,
            "submittedCount": len(reports),
            "expectedCount": len(scope_users),
            "model": result.model,
            "usage": result.usage,
        },
    )
    return summary
