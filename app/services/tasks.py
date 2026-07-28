from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import is_privileged, jsonable_snapshot
from app.errors import AppError, NotFoundError, PermissionDeniedError
from app.models import (
    ProjectStatus,
    Task,
    TaskAssignmentHistory,
    TaskCollaborator,
    TaskStatus,
    User,
    utc_now,
)
from app.schemas import TaskCreate, TaskTransition, TaskUpdate
from app.services.projects import assert_revision, ensure_user, get_project

TASK_SNAPSHOT_FIELDS = (
    "id",
    "project_id",
    "title",
    "description",
    "owner_id",
    "created_by",
    "priority",
    "status",
    "due_date",
    "blocker_reason",
    "result",
    "cancel_reason",
    "started_at",
    "completed_at",
    "revision",
)

TASK_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.TODO.value: {
        TaskStatus.IN_PROGRESS.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.IN_PROGRESS.value: {
        TaskStatus.BLOCKED.value,
        TaskStatus.DONE.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.BLOCKED.value: {
        TaskStatus.IN_PROGRESS.value,
        TaskStatus.CANCELLED.value,
    },
    TaskStatus.DONE.value: set(),
    TaskStatus.CANCELLED.value: set(),
}


def get_task(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if not task or task.deleted_at:
        raise NotFoundError("TASK_NOT_FOUND", "任务不存在")
    return task


def can_manage_task(db: Session, user: User, task: Task) -> bool:
    if is_privileged(user) or task.owner_id == user.id:
        return True
    project = get_project(db, task.project_id)
    return project.owner_id == user.id


def require_manage_task(db: Session, user: User, task: Task) -> None:
    if not can_manage_task(db, user, task):
        raise PermissionDeniedError("只有任务负责人、项目负责人或管理者可以修改任务")


def _replace_collaborators(
    db: Session,
    task: Task,
    collaborator_ids: list[str],
    actor: User,
) -> None:
    ids = list(dict.fromkeys(collaborator_ids))
    for user_id in ids:
        ensure_user(db, user_id)
    db.execute(delete(TaskCollaborator).where(TaskCollaborator.task_id == task.id))
    for user_id in ids:
        if user_id == task.owner_id:
            continue
        db.add(TaskCollaborator(task_id=task.id, user_id=user_id, added_by=actor.id))


def create_task(db: Session, payload: TaskCreate, actor: User) -> Task:
    project = get_project(db, payload.project_id)
    if project.status in {
        ProjectStatus.REJECTED.value,
        ProjectStatus.MERGED.value,
        ProjectStatus.ARCHIVED.value,
        ProjectStatus.COMPLETED.value,
    }:
        raise AppError("PROJECT_NOT_WRITABLE", "当前项目状态不允许创建任务")
    ensure_user(db, payload.owner_id)
    task = Task(
        project_id=project.id,
        title=payload.title.strip(),
        description=payload.description,
        owner_id=payload.owner_id,
        created_by=actor.id,
        priority=payload.priority.value,
        due_date=payload.due_date,
    )
    db.add(task)
    db.flush()
    _replace_collaborators(db, task, payload.collaborator_ids, actor)
    db.add(
        TaskAssignmentHistory(
            task_id=task.id,
            previous_owner_id=None,
            new_owner_id=task.owner_id,
            reason="initial_assignment",
            changed_by=actor.id,
        )
    )
    record_audit(
        db,
        actor=actor,
        action="task.create",
        entity_type="task",
        entity_id=task.id,
        after_data=jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS),
        detail={"collaboratorIds": payload.collaborator_ids},
    )
    return task


def list_tasks(
    db: Session,
    *,
    project_id: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
) -> list[Task]:
    query = select(Task).where(Task.deleted_at.is_(None))
    if project_id:
        query = query.where(Task.project_id == project_id)
    if owner_id:
        query = query.where(Task.owner_id == owner_id)
    if status:
        query = query.where(Task.status == status)
    return list(db.scalars(query.order_by(Task.updated_at.desc()).limit(500)).all())


def update_task(db: Session, task: Task, payload: TaskUpdate, actor: User) -> Task:
    require_manage_task(db, actor, task)
    assert_revision(task, payload.revision, entity_name="task")
    before = jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS)
    fields = payload.model_fields_set - {"revision"}
    for field in ("title", "description", "due_date"):
        if field in fields:
            value = getattr(payload, field)
            if field == "title" and value:
                value = value.strip()
            setattr(task, field, value)
    if "priority" in fields and payload.priority:
        task.priority = payload.priority.value
    if "collaborator_ids" in fields and payload.collaborator_ids is not None:
        _replace_collaborators(db, task, payload.collaborator_ids, actor)
    task.revision += 1
    task.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="task.update",
        entity_type="task",
        entity_id=task.id,
        before_data=before,
        after_data=jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS),
    )
    return task


def transition_task(
    db: Session,
    task: Task,
    payload: TaskTransition,
    actor: User,
) -> Task:
    require_manage_task(db, actor, task)
    assert_revision(task, payload.revision, entity_name="task")
    target = payload.status.value
    if target not in TASK_TRANSITIONS.get(task.status, set()):
        raise AppError("INVALID_TASK_TRANSITION", f"任务不能从 {task.status} 转为 {target}")
    if target == TaskStatus.BLOCKED.value and not payload.blocker_reason:
        raise AppError("BLOCKER_REASON_REQUIRED", "阻塞任务必须填写阻塞原因")
    if target == TaskStatus.DONE.value and not payload.result:
        raise AppError("TASK_RESULT_REQUIRED", "完成任务必须填写完成结果")
    if target == TaskStatus.CANCELLED.value and not payload.cancel_reason:
        raise AppError("TASK_CANCEL_REASON_REQUIRED", "取消任务必须填写取消原因")

    before = jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS)
    task.status = target
    if target == TaskStatus.IN_PROGRESS.value:
        task.started_at = task.started_at or utc_now()
        task.blocker_reason = None
    elif target == TaskStatus.BLOCKED.value:
        task.blocker_reason = payload.blocker_reason
    elif target == TaskStatus.DONE.value:
        task.result = payload.result
        task.completed_at = utc_now()
        task.blocker_reason = None
    elif target == TaskStatus.CANCELLED.value:
        task.cancel_reason = payload.cancel_reason
    task.revision += 1
    task.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="task.transition",
        entity_type="task",
        entity_id=task.id,
        before_data=before,
        after_data=jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS),
    )
    return task


def reassign_task(
    db: Session,
    task: Task,
    *,
    owner_id: str,
    revision: int,
    reason: str | None,
    actor: User,
) -> Task:
    require_manage_task(db, actor, task)
    assert_revision(task, revision, entity_name="task")
    ensure_user(db, owner_id)
    if task.owner_id == owner_id:
        raise AppError("TASK_OWNER_UNCHANGED", "任务负责人没有变化")
    before = jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS)
    previous_owner = task.owner_id
    task.owner_id = owner_id
    task.revision += 1
    task.updated_at = utc_now()
    db.add(
        TaskAssignmentHistory(
            task_id=task.id,
            previous_owner_id=previous_owner,
            new_owner_id=owner_id,
            reason=reason,
            changed_by=actor.id,
        )
    )
    record_audit(
        db,
        actor=actor,
        action="task.reassign",
        entity_type="task",
        entity_id=task.id,
        before_data=before,
        after_data=jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS),
        detail={"reason": reason},
    )
    return task
