from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Project,
    ProjectMember,
    ProjectTag,
    ProjectTagAssignment,
    Task,
    TaskCollaborator,
    User,
    WorkRecord,
)


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _project_rows(db: Session, project_ids: set[str]) -> list[dict[str, Any]]:
    if not project_ids:
        return []
    projects = db.scalars(
        select(Project)
        .where(Project.id.in_(project_ids), Project.deleted_at.is_(None))
        .order_by(Project.code)
    ).all()
    tag_rows = db.execute(
        select(ProjectTagAssignment.project_id, ProjectTag.name)
        .join(ProjectTag, ProjectTag.id == ProjectTagAssignment.tag_id)
        .where(ProjectTagAssignment.project_id.in_(project_ids))
        .order_by(ProjectTag.sort_order, ProjectTag.name)
    ).all()
    tags_by_project: dict[str, list[str]] = {}
    for project_id, tag_name in tag_rows:
        tags_by_project.setdefault(project_id, []).append(tag_name)
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


def _task_row(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "owner_id": task.owner_id,
        "priority": task.priority,
        "status": task.status,
        "due_date": task.due_date,
        "blocker_reason": task.blocker_reason,
        "result": task.result,
    }


def _work_record_row(record: WorkRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "work_date": record.work_date,
        "content": record.content,
        "hours": record.minutes / 60,
        "project_id": record.project_id,
        "task_id": record.task_id,
        "risk": record.risk,
        "next_action": record.next_action,
    }


def build_chat_context(db: Session, actor: User) -> str:
    """Build server-owned context for free-form chat.

    A project is related when the user owns or joins it, owns/collaborates on one
    of its tasks, or has a work record linked to it. The browser cannot inject or
    broaden this scope.
    """

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

    tasks = (
        db.scalars(
            select(Task)
            .where(
                Task.project_id.in_(project_ids),
                Task.deleted_at.is_(None),
            )
            .order_by(Task.updated_at.desc())
            .limit(200)
        ).all()
        if project_ids
        else []
    )
    local_today = datetime.now(timezone(timedelta(hours=8))).date()
    recent_since = local_today - timedelta(days=90)
    records = db.scalars(
        select(WorkRecord)
        .where(
            WorkRecord.author_id == actor.id,
            WorkRecord.work_date >= recent_since,
            WorkRecord.deleted_at.is_(None),
        )
        .order_by(WorkRecord.work_date.desc(), WorkRecord.created_at.desc())
        .limit(200)
    ).all()
    return _json_text(
        {
            "scope": "仅限当前用户有关的项目、任务及其最近90天工作记录",
            "current_user": {
                "id": actor.id,
                "display_name": actor.display_name,
            },
            "projects": _project_rows(db, project_ids),
            "tasks": [_task_row(task) for task in tasks],
            "work_records": [_work_record_row(record) for record in records],
        }
    )


def build_weekly_report_context(
    db: Session,
    actor: User,
    week_start: date,
    week_end: date,
) -> str:
    records = db.scalars(
        select(WorkRecord)
        .where(
            WorkRecord.author_id == actor.id,
            WorkRecord.work_date >= week_start,
            WorkRecord.work_date <= week_end,
            WorkRecord.deleted_at.is_(None),
        )
        .order_by(WorkRecord.work_date, WorkRecord.created_at)
    ).all()
    project_ids = {record.project_id for record in records if record.project_id}
    task_ids = {record.task_id for record in records if record.task_id}
    tasks = (
        db.scalars(
            select(Task)
            .where(Task.id.in_(task_ids), Task.deleted_at.is_(None))
            .order_by(Task.created_at)
        ).all()
        if task_ids
        else []
    )
    return _json_text(
        {
            "scope": "仅限当前用户本自然周的工作记录；项目仅在本周存在该用户工作记录时提供",
            "current_user": {
                "id": actor.id,
                "display_name": actor.display_name,
            },
            "week_start": week_start,
            "week_end": week_end,
            "projects": _project_rows(db, project_ids),
            "tasks": [_task_row(task) for task in tasks],
            "work_records": [_work_record_row(record) for record in records],
        }
    )
