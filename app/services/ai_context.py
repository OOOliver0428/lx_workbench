from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    DepartmentWorkVisibility,
    PermissionKey,
    Project,
    ProjectMember,
    ProjectStatus,
    ProjectTag,
    ProjectTagAssignment,
    Task,
    TaskCollaborator,
    TaskPriority,
    TaskStatus,
    User,
    WorkRecord,
)
from app.services import department_works as department_work_service
from app.services.permissions import has_permission

CONTEXT_PROJECT_LIMIT = 100
CONTEXT_DEPARTMENT_WORK_LIMIT = 100
CONTEXT_TASK_LIMIT = 200
CONTEXT_RECORD_LIMIT = 200
CONTEXT_TAG_LIMIT_PER_PROJECT = 20

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

PROJECT_STATUS_LABELS = {
    ProjectStatus.PENDING.value: "待确认",
    ProjectStatus.ACTIVE.value: "进行中",
    ProjectStatus.PAUSED.value: "已暂停",
    ProjectStatus.COMPLETED.value: "已完成",
    ProjectStatus.ARCHIVED.value: "已归档",
    ProjectStatus.REJECTED.value: "已驳回",
    ProjectStatus.MERGED.value: "已合并",
}
DEPARTMENT_WORK_STATUS_LABELS = {
    DepartmentWorkStatus.IN_PROGRESS.value: "进行中",
    DepartmentWorkStatus.COMPLETED.value: "已完成",
    DepartmentWorkStatus.ARCHIVED.value: "已归档",
}
DEPARTMENT_WORK_VISIBILITY_LABELS = {
    DepartmentWorkVisibility.DEPARTMENT_ONLY.value: "仅本部门可见",
    DepartmentWorkVisibility.PUBLIC.value: "全公司可见",
}
TASK_STATUS_LABELS = {
    TaskStatus.TODO.value: "待开始",
    TaskStatus.IN_PROGRESS.value: "处理中",
    TaskStatus.BLOCKED.value: "阻塞",
    TaskStatus.DONE.value: "已完成",
    TaskStatus.CANCELLED.value: "已取消",
}
TASK_PRIORITY_LABELS = {
    TaskPriority.P0.value: "P0",
    TaskPriority.P1.value: "P1",
    TaskPriority.P2.value: "P2",
}


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _local_today() -> date:
    return datetime.now(SHANGHAI).date()


def _week_bounds(today: date) -> tuple[date, date]:
    week_start = today - timedelta(days=today.weekday())
    return week_start, week_start + timedelta(days=6)


def _local_date_iso(value: datetime | None) -> str | None:
    """Return a timezone-aware datetime as an Asia/Shanghai date string."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SHANGHAI).date().isoformat()


def _owner_names(db: Session, user_ids: set[str]) -> dict[str, str]:
    """Map user ids to display names; disambiguate duplicates with login names."""
    if not user_ids:
        return {}
    rows = db.execute(
        select(User.id, User.display_name, User.login_name).where(
            User.id.in_(user_ids)
        )
    ).all()
    occurrences: dict[str, int] = {}
    for _user_id, display_name, _login_name in rows:
        occurrences[display_name] = occurrences.get(display_name, 0) + 1
    names: dict[str, str] = {}
    for user_id, display_name, login_name in rows:
        names[user_id] = (
            f"{display_name}（{login_name}）"
            if occurrences[display_name] > 1
            else display_name
        )
    return names


def _project_names(db: Session, project_ids: set[str]) -> dict[str, str]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(Project.id, Project.name).where(
            Project.id.in_(project_ids), Project.deleted_at.is_(None)
        )
    ).all()
    return {project_id: name for project_id, name in rows}


def _task_titles(db: Session, task_ids: set[str]) -> dict[str, str]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(Task.id, Task.title).where(
            Task.id.in_(task_ids), Task.deleted_at.is_(None)
        )
    ).all()
    return {task_id: title for task_id, title in rows}


def _department_names(db: Session, department_ids: set[str]) -> dict[str, str]:
    if not department_ids:
        return {}
    rows = db.execute(
        select(Department.id, Department.name).where(
            Department.id.in_(department_ids)
        )
    ).all()
    return {department_id: name for department_id, name in rows}


def _load_projects(db: Session, project_ids: set[str]) -> list[Project]:
    if not project_ids:
        return []
    return list(
        db.scalars(
            select(Project)
            .where(Project.id.in_(project_ids), Project.deleted_at.is_(None))
            .order_by(Project.code)
            .limit(CONTEXT_PROJECT_LIMIT)
        ).all()
    )


def _load_project_tags(
    db: Session, project_ids: set[str]
) -> dict[str, list[str]]:
    if not project_ids:
        return {}
    tag_rows = db.execute(
        select(ProjectTagAssignment.project_id, ProjectTag.name)
        .join(ProjectTag, ProjectTag.id == ProjectTagAssignment.tag_id)
        .where(ProjectTagAssignment.project_id.in_(project_ids))
        .order_by(ProjectTag.sort_order, ProjectTag.name)
        .limit(CONTEXT_PROJECT_LIMIT * CONTEXT_TAG_LIMIT_PER_PROJECT)
    ).all()
    tags_by_project: dict[str, list[str]] = {}
    for project_id, tag_name in tag_rows:
        tags = tags_by_project.setdefault(project_id, [])
        if len(tags) < CONTEXT_TAG_LIMIT_PER_PROJECT:
            tags.append(tag_name)
    return tags_by_project


def _load_department_works(
    db: Session,
    actor: User,
    department_work_ids: set[str],
) -> tuple[list[DepartmentWork], bool]:
    """Return (works the actor may currently see, whether the list was truncated)."""
    if not department_work_ids:
        return [], False
    works = db.scalars(
        select(DepartmentWork)
        .where(
            DepartmentWork.id.in_(department_work_ids),
            DepartmentWork.deleted_at.is_(None),
        )
        .order_by(DepartmentWork.code)
    ).all()
    visible_works = [
        work
        for work in works
        if department_work_service.can_view_department_work(db, actor, work)
    ]
    truncated = len(visible_works) > CONTEXT_DEPARTMENT_WORK_LIMIT
    return visible_works[:CONTEXT_DEPARTMENT_WORK_LIMIT], truncated


def _render_project(
    project: Project,
    tags: list[str],
    owner_names: dict[str, str],
    actor_id: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": project.code,
        "name": project.name,
        "owner_name": owner_names.get(project.owner_id, "未知负责人"),
        "mine": project.owner_id == actor_id,
        "status": PROJECT_STATUS_LABELS.get(project.status, project.status),
    }
    if project.description:
        row["description"] = project.description
    if project.planned_start_date:
        row["planned_start_date"] = project.planned_start_date.isoformat()
    if project.planned_end_date:
        row["planned_end_date"] = project.planned_end_date.isoformat()
    if tags:
        row["tags"] = tags
    return row


def _render_department_work(
    work: DepartmentWork,
    department_names: dict[str, str],
    owner_names: dict[str, str],
    actor_id: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": work.code,
        "name": work.name,
        "department_name": department_names.get(work.department_id, "未知部门"),
        "owner_name": owner_names.get(work.owner_id, "未知负责人"),
        "mine": work.owner_id == actor_id,
        "status": DEPARTMENT_WORK_STATUS_LABELS.get(work.status, work.status),
        "visibility": DEPARTMENT_WORK_VISIBILITY_LABELS.get(
            work.visibility, work.visibility
        ),
    }
    if work.description:
        row["description"] = work.description
    return row


def _render_task(
    task: Task,
    *,
    owner_names: dict[str, str],
    actor_id: str,
    project_names: dict[str, str],
    department_work_names: dict[str, str],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "title": task.title,
        "owner_name": owner_names.get(task.owner_id, "未知负责人"),
        "mine": task.owner_id == actor_id,
        "priority": TASK_PRIORITY_LABELS.get(task.priority, task.priority),
        "status": TASK_STATUS_LABELS.get(task.status, task.status),
        "level": task.level,
    }
    updated_at = _local_date_iso(task.updated_at)
    if updated_at:
        row["updated_at"] = updated_at
    if task.description:
        row["description"] = task.description
    if task.project_id and task.project_id in project_names:
        row["project_name"] = project_names[task.project_id]
    if (
        task.department_work_id
        and task.department_work_id in department_work_names
    ):
        row["department_work_name"] = department_work_names[task.department_work_id]
    if task.due_date:
        row["due_date"] = task.due_date.isoformat()
    if task.started_at:
        row["started_at"] = _local_date_iso(task.started_at)
    if task.completed_at:
        row["completed_at"] = _local_date_iso(task.completed_at)
    if task.progress_enabled and task.progress_percent is not None:
        row["progress_percent"] = task.progress_percent
    if task.blocker_reason:
        row["blocker_reason"] = task.blocker_reason
    if task.result:
        row["result"] = task.result
    return row


def _render_work_record(
    record: WorkRecord,
    *,
    project_names: dict[str, str],
    department_work_names: dict[str, str],
    task_titles: dict[str, str],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "work_date": record.work_date.isoformat(),
        "content": record.content,
        "hours": record.minutes / 60,
    }
    if record.project_id and record.project_id in project_names:
        row["project_name"] = project_names[record.project_id]
    if (
        record.department_work_id
        and record.department_work_id in department_work_names
    ):
        row["department_work_name"] = department_work_names[record.department_work_id]
    if record.task_id and record.task_id in task_titles:
        row["task_title"] = task_titles[record.task_id]
    if record.risk:
        row["risk"] = record.risk
    if record.next_action:
        row["next_action"] = record.next_action
    return row


def _assemble_context(
    db: Session,
    actor: User,
    *,
    scope: str,
    week_start: date,
    week_end: date,
    projects: list[Project],
    works: list[DepartmentWork],
    tasks: list[Task],
    records: list[WorkRecord],
    can_view_projects: bool,
    can_view_tasks: bool,
    projects_truncated: bool = False,
    department_works_truncated: bool = False,
    tasks_truncated: bool = False,
    records_truncated: bool = False,
) -> str:
    tags_by_project = _load_project_tags(db, {project.id for project in projects})
    owner_ids = (
        {project.owner_id for project in projects}
        | {work.owner_id for work in works}
        | {task.owner_id for task in tasks}
    )
    owner_names = _owner_names(db, owner_ids)
    department_names = _department_names(db, {work.department_id for work in works})

    project_names = {project.id: project.name for project in projects}
    if can_view_projects:
        missing_project_ids = (
            {record.project_id for record in records if record.project_id}
            - project_names.keys()
        )
        if missing_project_ids:
            project_names.update(_project_names(db, missing_project_ids))
    department_work_names = {work.id: work.name for work in works}
    task_titles = {task.id: task.title for task in tasks} if can_view_tasks else {}
    if can_view_tasks:
        missing_task_ids = (
            {record.task_id for record in records if record.task_id}
            - task_titles.keys()
        )
        if missing_task_ids:
            task_titles.update(_task_titles(db, missing_task_ids))

    truncated_sections = [
        name
        for name, truncated in (
            ("projects", projects_truncated),
            ("department_works", department_works_truncated),
            ("tasks", tasks_truncated),
            ("work_records", records_truncated),
        )
        if truncated
    ]
    scope_text = scope
    if truncated_sections:
        scope_text += "；truncated_sections 列出的部分已按规则截断，未包含的数据不得假设存在"

    today = _local_today()
    payload: dict[str, Any] = {
        "scope": scope_text,
        "today": today.isoformat(),
        "weekday": WEEKDAY_LABELS[today.weekday()],
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "current_user": {"display_name": actor.display_name},
        "counts": {
            "projects": len(projects),
            "department_works": len(works),
            "tasks": len(tasks),
            "work_records": len(records),
        },
        "truncated_sections": truncated_sections,
        "projects": [
            _render_project(
                project,
                tags_by_project.get(project.id, []),
                owner_names,
                actor.id,
            )
            for project in projects
        ],
        "department_works": [
            _render_department_work(work, department_names, owner_names, actor.id)
            for work in works
        ],
        "tasks": [
            _render_task(
                task,
                owner_names=owner_names,
                actor_id=actor.id,
                project_names=project_names,
                department_work_names=department_work_names,
            )
            for task in tasks
        ],
        "work_records": [
            _render_work_record(
                record,
                project_names=project_names,
                department_work_names=department_work_names,
                task_titles=task_titles,
            )
            for record in records
        ],
    }
    return _json_text(payload)


def build_chat_context(db: Session, actor: User) -> str:
    """Build server-owned context for free-form chat.

    A project is related when the user owns or joins it, owns/collaborates on one
    of its tasks, or has a work record linked to it. The browser cannot inject or
    broaden this scope. Rows carry display names and localized labels instead of
    raw ids so the model can read them directly.
    """

    can_view_projects = has_permission(db, actor, PermissionKey.PROJECTS_VIEW)
    can_view_department_works = has_permission(
        db, actor, PermissionKey.DEPARTMENT_WORKS_VIEW
    )
    can_view_tasks = has_permission(db, actor, PermissionKey.TASKS_VIEW)
    can_view_records = has_permission(db, actor, PermissionKey.WORK_RECORDS_VIEW)
    project_ids = set(
        db.scalars(
            select(Project.id).where(
                Project.owner_id == actor.id,
                Project.deleted_at.is_(None),
            )
        ).all()
    )
    project_ids.update(
        db.scalars(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == actor.id,
                ProjectMember.left_at.is_(None),
            )
        ).all()
    )
    project_ids.update(
        db.scalars(
            select(Task.project_id).where(
                Task.owner_id == actor.id,
                Task.deleted_at.is_(None),
            )
        ).all()
    )
    project_ids.update(
        db.scalars(
            select(Task.project_id)
            .join(TaskCollaborator, TaskCollaborator.task_id == Task.id)
            .where(
                TaskCollaborator.user_id == actor.id,
                Task.deleted_at.is_(None),
            )
        ).all()
    )
    project_ids.update(
        db.scalars(
            select(WorkRecord.project_id).where(
                WorkRecord.author_id == actor.id,
                WorkRecord.project_id.is_not(None),
                WorkRecord.deleted_at.is_(None),
            )
        ).all()
    )
    project_ids.discard(None)
    related_project_ids = sorted(project_ids)
    projects_truncated = len(related_project_ids) > CONTEXT_PROJECT_LIMIT
    project_ids = set(related_project_ids[:CONTEXT_PROJECT_LIMIT])

    department_work_ids = set(
        db.scalars(
            select(DepartmentWork.id).where(
                DepartmentWork.owner_id == actor.id,
                DepartmentWork.deleted_at.is_(None),
            )
        ).all()
    )
    # Department work is shared by a department, so every visible source in the
    # actor's primary department is relevant without an explicit assignment.
    if actor.primary_department_id:
        department_work_ids.update(
            db.scalars(
                select(DepartmentWork.id).where(
                    DepartmentWork.department_id == actor.primary_department_id,
                    DepartmentWork.deleted_at.is_(None),
                )
            ).all()
        )
    department_work_ids.update(
        db.scalars(
            select(Task.department_work_id).where(
                Task.owner_id == actor.id,
                Task.department_work_id.is_not(None),
                Task.deleted_at.is_(None),
            )
        ).all()
    )
    department_work_ids.update(
        db.scalars(
            select(Task.department_work_id)
            .join(TaskCollaborator, TaskCollaborator.task_id == Task.id)
            .where(
                TaskCollaborator.user_id == actor.id,
                Task.department_work_id.is_not(None),
                Task.deleted_at.is_(None),
            )
        ).all()
    )
    department_work_ids.update(
        db.scalars(
            select(WorkRecord.department_work_id).where(
                WorkRecord.author_id == actor.id,
                WorkRecord.department_work_id.is_not(None),
                WorkRecord.deleted_at.is_(None),
            )
        ).all()
    )
    department_work_ids.discard(None)
    works, department_works_truncated = (
        _load_department_works(db, actor, department_work_ids)
        if can_view_department_works
        else ([], False)
    )
    visible_department_work_ids = {work.id for work in works}

    task_source_filters: list[Any] = []
    if project_ids:
        task_source_filters.append(Task.project_id.in_(project_ids))
    if visible_department_work_ids:
        task_source_filters.append(
            Task.department_work_id.in_(visible_department_work_ids)
        )
    tasks = (
        db.scalars(
            select(Task)
            .where(
                or_(*task_source_filters),
                Task.deleted_at.is_(None),
            )
            .order_by(Task.updated_at.desc())
            .limit(CONTEXT_TASK_LIMIT + 1)
        ).all()
        if task_source_filters and can_view_tasks
        else []
    )
    tasks_truncated = len(tasks) > CONTEXT_TASK_LIMIT
    tasks = list(tasks[:CONTEXT_TASK_LIMIT])

    today = _local_today()
    week_start, week_end = _week_bounds(today)
    recent_since = today - timedelta(days=90)
    records = (
        db.scalars(
            select(WorkRecord)
            .where(
                WorkRecord.author_id == actor.id,
                WorkRecord.work_date >= recent_since,
                WorkRecord.deleted_at.is_(None),
            )
            .order_by(WorkRecord.work_date.desc(), WorkRecord.created_at.desc())
            .limit(CONTEXT_RECORD_LIMIT + 1)
        ).all()
        if can_view_records
        else []
    )
    records_truncated = len(records) > CONTEXT_RECORD_LIMIT
    records = list(records[:CONTEXT_RECORD_LIMIT])

    projects = _load_projects(db, project_ids) if can_view_projects else []

    return _assemble_context(
        db,
        actor,
        scope=(
            "仅限与当前用户有关的项目、部门工作、任务及其最近90天工作记录；"
            "负责人以姓名显示，任务与记录通过名称关联所属项目或部门工作；"
            "日期相关判断以 today 与 week 字段为准"
        ),
        week_start=week_start,
        week_end=week_end,
        projects=projects,
        works=works,
        tasks=tasks,
        records=records,
        can_view_projects=can_view_projects,
        can_view_tasks=can_view_tasks,
        projects_truncated=projects_truncated,
        department_works_truncated=department_works_truncated,
        tasks_truncated=tasks_truncated,
        records_truncated=records_truncated,
    )


def build_weekly_report_context(
    db: Session,
    actor: User,
    week_start: date,
    week_end: date,
) -> str:
    can_view_projects = has_permission(db, actor, PermissionKey.PROJECTS_VIEW)
    can_view_department_works = has_permission(
        db, actor, PermissionKey.DEPARTMENT_WORKS_VIEW
    )
    can_view_tasks = has_permission(db, actor, PermissionKey.TASKS_VIEW)
    records = list(
        db.scalars(
            select(WorkRecord)
            .where(
                WorkRecord.author_id == actor.id,
                WorkRecord.work_date >= week_start,
                WorkRecord.work_date <= week_end,
                WorkRecord.deleted_at.is_(None),
            )
            .order_by(WorkRecord.work_date, WorkRecord.created_at)
            .limit(CONTEXT_RECORD_LIMIT + 1)
        ).all()
    )
    records_truncated = len(records) > CONTEXT_RECORD_LIMIT
    records = records[:CONTEXT_RECORD_LIMIT]
    project_ids = {record.project_id for record in records if record.project_id}
    department_work_ids = {
        record.department_work_id for record in records if record.department_work_id
    }
    task_ids = {record.task_id for record in records if record.task_id}
    tasks = (
        list(
            db.scalars(
                select(Task)
                .where(Task.id.in_(task_ids), Task.deleted_at.is_(None))
                .order_by(Task.created_at)
            ).all()
        )
        if task_ids and can_view_tasks
        else []
    )
    # A record linked through a task remains attributable even for legacy rows
    # whose source column was not backfilled.
    department_work_ids.update(
        task.department_work_id for task in tasks if task.department_work_id
    )
    works, department_works_truncated = (
        _load_department_works(db, actor, department_work_ids)
        if can_view_department_works
        else ([], False)
    )
    visible_department_work_ids = {work.id for work in works}
    tasks = [
        task
        for task in tasks
        if task.department_work_id is None
        or task.department_work_id in visible_department_work_ids
    ]
    projects_truncated = len(project_ids) > CONTEXT_PROJECT_LIMIT
    projects = _load_projects(db, project_ids) if can_view_projects else []
    return _assemble_context(
        db,
        actor,
        scope=(
            "仅限当前用户本自然周的工作记录；项目和部门工作仅在本周存在关联记录时提供；"
            "负责人以姓名显示，任务与记录通过名称关联所属项目或部门工作；"
            "日期相关判断以 today 与 week 字段为准"
        ),
        week_start=week_start,
        week_end=week_end,
        projects=projects,
        works=works,
        tasks=tasks,
        records=records,
        can_view_projects=can_view_projects,
        can_view_tasks=can_view_tasks,
        projects_truncated=projects_truncated,
        department_works_truncated=department_works_truncated,
        records_truncated=records_truncated,
    )
