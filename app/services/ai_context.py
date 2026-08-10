from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    DepartmentWork,
    PermissionKey,
    Project,
    ProjectMember,
    ProjectTag,
    ProjectTagAssignment,
    Task,
    TaskCollaborator,
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


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _project_rows(db: Session, project_ids: set[str]) -> list[dict[str, Any]]:
    if not project_ids:
        return []
    projects = db.scalars(
        select(Project)
        .where(Project.id.in_(project_ids), Project.deleted_at.is_(None))
        .order_by(Project.code)
        .limit(CONTEXT_PROJECT_LIMIT)
    ).all()
    loaded_project_ids = {project.id for project in projects}
    if not loaded_project_ids:
        return []
    tag_rows = db.execute(
        select(ProjectTagAssignment.project_id, ProjectTag.name)
        .join(ProjectTag, ProjectTag.id == ProjectTagAssignment.tag_id)
        .where(ProjectTagAssignment.project_id.in_(loaded_project_ids))
        .order_by(ProjectTag.sort_order, ProjectTag.name)
        .limit(CONTEXT_PROJECT_LIMIT * CONTEXT_TAG_LIMIT_PER_PROJECT)
    ).all()
    tags_by_project: dict[str, list[str]] = {}
    for project_id, tag_name in tag_rows:
        tags = tags_by_project.setdefault(project_id, [])
        if len(tags) < CONTEXT_TAG_LIMIT_PER_PROJECT:
            tags.append(tag_name)
    return [
        {
            "id": project.id,
            "code": project.code,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "owner_id": project.owner_id,
            "planned_start_date": project.planned_start_date,
            "planned_end_date": project.planned_end_date,
            "tags": tags_by_project.get(project.id, []),
        }
        for project in projects
    ]


def _department_work_rows(
    db: Session,
    actor: User,
    department_work_ids: set[str],
) -> list[dict[str, Any]]:
    """Return only department work rows the actor may currently see."""

    if not department_work_ids:
        return []
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
    ][:CONTEXT_DEPARTMENT_WORK_LIMIT]
    return [
        {
            "id": work.id,
            "code": work.code,
            "name": work.name,
            "description": work.description,
            "department_id": work.department_id,
            "owner_id": work.owner_id,
            "status": work.status,
            "visibility": work.visibility,
        }
        for work in visible_works
    ]


def _task_row(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "department_work_id": task.department_work_id,
        "parent_id": task.parent_id,
        "level": task.level,
        "title": task.title,
        "description": task.description,
        "owner_id": task.owner_id,
        "priority": task.priority,
        "status": task.status,
        "due_date": task.due_date,
        "blocker_reason": task.blocker_reason,
        "result": task.result,
        "progress_enabled": task.progress_enabled,
        "progress_percent": task.progress_percent,
    }


def _work_record_row(
    record: WorkRecord,
    *,
    include_project_id: bool,
    include_department_work_id: bool,
    include_task_id: bool,
) -> dict[str, Any]:
    row = {
        "id": record.id,
        "work_date": record.work_date,
        "content": record.content,
        "hours": record.minutes / 60,
        "risk": record.risk,
        "next_action": record.next_action,
    }
    if include_project_id:
        row["project_id"] = record.project_id
    if include_department_work_id:
        row["department_work_id"] = record.department_work_id
    if include_task_id:
        row["task_id"] = record.task_id
    return row


def build_chat_context(db: Session, actor: User) -> str:
    """Build server-owned context for free-form chat.

    A project is related when the user owns or joins it, owns/collaborates on one
    of its tasks, or has a work record linked to it. The browser cannot inject or
    broaden this scope.
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
    project_ids = set(sorted(project_ids)[:CONTEXT_PROJECT_LIMIT])

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
    department_work_rows = (
        _department_work_rows(db, actor, department_work_ids)
        if can_view_department_works
        else []
    )
    visible_department_work_ids = {
        row["id"] for row in department_work_rows
    }

    task_source_filters = []
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
            .limit(CONTEXT_TASK_LIMIT)
        ).all()
        if task_source_filters and can_view_tasks
        else []
    )
    local_today = datetime.now(timezone(timedelta(hours=8))).date()
    recent_since = local_today - timedelta(days=90)
    records = (
        db.scalars(
            select(WorkRecord)
            .where(
                WorkRecord.author_id == actor.id,
                WorkRecord.work_date >= recent_since,
                WorkRecord.deleted_at.is_(None),
            )
            .order_by(WorkRecord.work_date.desc(), WorkRecord.created_at.desc())
            .limit(CONTEXT_RECORD_LIMIT)
        ).all()
        if can_view_records
        else []
    )
    return _json_text(
        {
            "scope": "仅限与当前用户有关的项目、部门工作、任务及其最近90天工作记录",
            "current_user": {
                "id": actor.id,
                "display_name": actor.display_name,
            },
            "projects": _project_rows(db, project_ids) if can_view_projects else [],
            "department_works": department_work_rows,
            "tasks": [_task_row(task) for task in tasks],
            "work_records": [
                _work_record_row(
                    record,
                    include_project_id=can_view_projects,
                    include_department_work_id=(
                        can_view_department_works
                        and (
                            record.department_work_id is None
                            or record.department_work_id
                            in visible_department_work_ids
                        )
                    ),
                    include_task_id=can_view_tasks,
                )
                for record in records
            ],
        }
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
    records = db.scalars(
        select(WorkRecord)
        .where(
            WorkRecord.author_id == actor.id,
            WorkRecord.work_date >= week_start,
            WorkRecord.work_date <= week_end,
            WorkRecord.deleted_at.is_(None),
        )
        .order_by(WorkRecord.work_date, WorkRecord.created_at)
        .limit(CONTEXT_RECORD_LIMIT)
    ).all()
    project_ids = {record.project_id for record in records if record.project_id}
    department_work_ids = {
        record.department_work_id for record in records if record.department_work_id
    }
    task_ids = {record.task_id for record in records if record.task_id}
    tasks = (
        db.scalars(
            select(Task)
            .where(Task.id.in_(task_ids), Task.deleted_at.is_(None))
            .order_by(Task.created_at)
        ).all()
        if task_ids and can_view_tasks
        else []
    )
    # A record linked through a task remains attributable even for legacy rows
    # whose source column was not backfilled.
    department_work_ids.update(
        task.department_work_id for task in tasks if task.department_work_id
    )
    department_work_rows = (
        _department_work_rows(db, actor, department_work_ids)
        if can_view_department_works
        else []
    )
    visible_department_work_ids = {
        row["id"] for row in department_work_rows
    }
    tasks = [
        task
        for task in tasks
        if task.department_work_id is None
        or task.department_work_id in visible_department_work_ids
    ]
    return _json_text(
        {
            "scope": "仅限当前用户本自然周的工作记录；项目和部门工作仅在本周存在关联记录时提供",
            "current_user": {
                "id": actor.id,
                "display_name": actor.display_name,
            },
            "week_start": week_start,
            "week_end": week_end,
            "projects": _project_rows(db, project_ids) if can_view_projects else [],
            "department_works": department_work_rows,
            "tasks": [_task_row(task) for task in tasks],
            "work_records": [
                _work_record_row(
                    record,
                    include_project_id=can_view_projects,
                    include_department_work_id=(
                        can_view_department_works
                        and (
                            record.department_work_id is None
                            or record.department_work_id
                            in visible_department_work_ids
                        )
                    ),
                    include_task_id=can_view_tasks,
                )
                for record in records
            ],
        }
    )
