from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta, timezone

from sqlalchemy import and_, case, delete, or_, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import is_privileged, jsonable_snapshot
from app.errors import AppError, NotFoundError, PermissionDeniedError
from app.models import (
    ProjectStatus,
    Task,
    TaskAssignmentHistory,
    TaskCollaborator,
    TaskProgressHistory,
    TaskStatus,
    User,
    utc_now,
)
from app.schemas import (
    TaskCreate,
    TaskProgressUpdate,
    TaskTimeScope,
    TaskTransition,
    TaskTreeDelete,
    TaskUpdate,
)
from app.services import department_works as department_work_service
from app.services.projects import assert_revision, ensure_user, get_project

SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
TERMINAL_TASK_STATUSES = {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}

TASK_SNAPSHOT_FIELDS = (
    "id",
    "project_id",
    "department_work_id",
    "parent_id",
    "level",
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
    "progress_enabled",
    "progress_percent",
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


def _can_view_department_work(db: Session, user: User, department_work: object) -> bool:
    return department_work_service.can_view_department_work(db, user, department_work)


def _can_manage_department_work(db: Session, user: User, department_work: object) -> bool:
    return department_work_service.can_manage_department_work(db, user, department_work)


def can_view_task(db: Session, user: User, task: Task) -> bool:
    """Apply source-level visibility without exposing a private department work."""

    if task.project_id:
        return True
    if not task.department_work_id:
        # A legacy/corrupted row must not become globally visible.
        return False
    department_work = department_work_service.get_department_work(db, task.department_work_id)
    return _can_view_department_work(db, user, department_work)


def get_task(db: Session, task_id: str, *, actor: User | None = None) -> Task:
    task = db.get(Task, task_id)
    if not task or task.deleted_at:
        raise NotFoundError("TASK_NOT_FOUND", "任务不存在")
    if actor is not None and not can_view_task(db, actor, task):
        # Return 404 so a private department task cannot be enumerated by ID.
        raise NotFoundError("TASK_NOT_FOUND", "任务不存在")
    return task


def can_manage_task(db: Session, user: User, task: Task) -> bool:
    if task.project_id:
        if task.owner_id == user.id:
            return True
        if is_privileged(user):
            return True
        project = get_project(db, task.project_id)
        return project.owner_id == user.id
    if not task.department_work_id:
        return False
    department_work = department_work_service.get_department_work(db, task.department_work_id)
    return _can_manage_department_work(db, user, department_work)


def require_manage_task(db: Session, user: User, task: Task) -> None:
    if not can_manage_task(db, user, task):
        raise PermissionDeniedError("只有任务负责人、工作来源负责人或有管理权限的用户可以修改任务")
    if task.department_work_id:
        department_work = department_work_service.get_department_work(
            db,
            task.department_work_id,
        )
        department_work_service.require_department_work_writable(department_work)


def _replace_collaborators(
    db: Session,
    task: Task,
    collaborator_ids: list[str],
    actor: User,
) -> None:
    ids = list(dict.fromkeys(collaborator_ids))
    for user_id in ids:
        collaborator = ensure_user(db, user_id)
        _require_user_can_view_task_source(db, collaborator, task)
    db.execute(delete(TaskCollaborator).where(TaskCollaborator.task_id == task.id))
    for user_id in ids:
        if user_id == task.owner_id:
            continue
        db.add(TaskCollaborator(task_id=task.id, user_id=user_id, added_by=actor.id))


def _require_user_can_view_task_source(db: Session, user: User, task: Task) -> None:
    if not task.department_work_id:
        return
    department_work = department_work_service.get_department_work(db, task.department_work_id)
    if not _can_view_department_work(db, user, department_work):
        raise AppError(
            "TASK_ASSIGNEE_SOURCE_INVISIBLE",
            "任务负责人和协作人必须能够查看任务所属的部门工作",
        )


def _require_user_can_own_task_source(db: Session, user: User, task: Task) -> None:
    if not task.department_work_id:
        return
    department_work = department_work_service.get_department_work(db, task.department_work_id)
    if user.primary_department_id != department_work.department_id:
        raise AppError(
            "TASK_ASSIGNEE_SOURCE_INVISIBLE",
            "部门工作任务的负责人必须是负责部门成员；公开范围仅扩大查看权限",
        )


def _validate_project_for_task(db: Session, project_id: str) -> None:
    project = get_project(db, project_id)
    if project.status in {
        ProjectStatus.REJECTED.value,
        ProjectStatus.MERGED.value,
        ProjectStatus.ARCHIVED.value,
        ProjectStatus.COMPLETED.value,
    }:
        raise AppError("PROJECT_NOT_WRITABLE", "当前项目状态不允许创建任务")


def _validate_department_work_for_task(
    db: Session,
    department_work_id: str,
    actor: User,
) -> None:
    department_work = department_work_service.get_department_work(db, department_work_id)
    department_work_service.require_create_in_department_work(db, actor, department_work)


def _resolve_task_source(
    db: Session,
    payload: TaskCreate,
    actor: User,
) -> tuple[str | None, str | None, str | None, int]:
    project_id = payload.project_id
    department_work_id = payload.department_work_id
    parent_id = payload.parent_id
    level = 0

    parent: Task | None = None
    if parent_id:
        parent = get_task(db, parent_id, actor=actor)
        if parent.status in TERMINAL_TASK_STATUSES:
            raise AppError(
                "TASK_PARENT_TERMINAL",
                "已完成或已取消的任务不能新增子任务",
            )
        if parent.level >= 2:
            raise AppError("TASK_LEVEL_LIMIT", "任务最多支持三级")
        level = parent.level + 1

        if project_id is None and department_work_id is None:
            project_id = parent.project_id
            department_work_id = parent.department_work_id
        elif project_id != parent.project_id or department_work_id != parent.department_work_id:
            raise AppError("TASK_PARENT_SOURCE_MISMATCH", "子任务必须与父任务属于同一来源")

    if (project_id is None) == (department_work_id is None):
        raise AppError(
            "TASK_SOURCE_INVALID",
            "任务必须且只能关联一个项目或部门工作",
        )
    if project_id:
        _validate_project_for_task(db, project_id)
    else:
        assert department_work_id is not None
        _validate_department_work_for_task(db, department_work_id, actor)
    return project_id, department_work_id, parent_id, level


def create_task(db: Session, payload: TaskCreate, actor: User) -> Task:
    project_id, department_work_id, parent_id, level = _resolve_task_source(db, payload, actor)
    owner_id = payload.owner_id or actor.id
    owner = ensure_user(db, owner_id)
    task = Task(
        project_id=project_id,
        department_work_id=department_work_id,
        parent_id=parent_id,
        level=level,
        title=payload.title.strip(),
        description=payload.description,
        owner_id=owner_id,
        created_by=actor.id,
        priority=payload.priority.value,
        due_date=payload.due_date,
        progress_enabled=False,
        progress_percent=None,
    )
    _require_user_can_own_task_source(db, owner, task)
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


def _normalized_ids(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    return list(dict.fromkeys(value for value in values if value))


def _today_in_shanghai() -> date:
    return utc_now().astimezone(SHANGHAI_TZ).date()


def list_tasks(
    db: Session,
    *,
    actor: User | None = None,
    project_id: str | None = None,
    project_ids: Iterable[str] | None = None,
    department_work_ids: Iterable[str] | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    time_scope: TaskTimeScope | str = TaskTimeScope.WEEK,
) -> list[Task]:
    query = select(Task).where(Task.deleted_at.is_(None))

    selected_project_ids = _normalized_ids(project_ids)
    if project_id and project_id not in selected_project_ids:
        selected_project_ids.append(project_id)
    selected_department_work_ids = _normalized_ids(department_work_ids)
    source_filters = []
    if selected_project_ids:
        source_filters.append(Task.project_id.in_(selected_project_ids))
    if selected_department_work_ids:
        source_filters.append(Task.department_work_id.in_(selected_department_work_ids))
    if source_filters:
        query = query.where(or_(*source_filters))

    if owner_id:
        query = query.where(Task.owner_id == owner_id)
    if status:
        query = query.where(Task.status == status)
    else:
        query = query.where(Task.status.not_in(TERMINAL_TASK_STATUSES))

    scope = time_scope.value if isinstance(time_scope, TaskTimeScope) else str(time_scope)
    today = _today_in_shanghai()
    incomplete_overdue = and_(
        Task.due_date < today,
        Task.status.not_in(TERMINAL_TASK_STATUSES),
    )
    if scope == TaskTimeScope.TODAY.value:
        query = query.where(or_(incomplete_overdue, Task.due_date == today))
    elif scope == TaskTimeScope.WEEK.value:
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        query = query.where(
            or_(
                incomplete_overdue,
                Task.due_date.between(week_start, week_end),
                Task.due_date.is_(None),
            )
        )
    elif scope != TaskTimeScope.ALL.value:
        raise AppError("INVALID_TASK_TIME_SCOPE", "不支持的任务时间范围")

    sort_bucket = case(
        (incomplete_overdue, 0),
        (Task.due_date.is_not(None), 1),
        else_=2,
    )
    query = query.order_by(
        sort_bucket.asc(),
        Task.due_date.asc(),
        Task.created_at.desc(),
    )

    # Visibility is delegated to the department-work policy. Iteration stops
    # after 500 visible rows so private rows neither leak nor consume the limit.
    visible: list[Task] = []
    for task in db.scalars(query):
        if actor is not None and not can_view_task(db, actor, task):
            continue
        visible.append(task)
        if len(visible) >= 500:
            break
    return visible


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


def _active_descendants(db: Session, task: Task) -> list[Task]:
    descendants: list[Task] = []
    pending_ids = [task.id]
    visited = {task.id}
    while pending_ids:
        children = list(
            db.scalars(
                select(Task)
                .where(
                    Task.parent_id.in_(pending_ids),
                    Task.deleted_at.is_(None),
                )
                .order_by(Task.level, Task.created_at, Task.id)
            ).all()
        )
        pending_ids = []
        for child in children:
            if child.id in visited:
                raise AppError(
                    "TASK_HIERARCHY_CORRUPTED",
                    "任务层级存在循环",
                    status_code=500,
                )
            visited.add(child.id)
            descendants.append(child)
            pending_ids.append(child.id)
    return descendants


def _record_progress_history(
    db: Session,
    *,
    task: Task,
    from_enabled: bool,
    from_percent: int | None,
    from_status: str,
    reason: str | None,
    actor: User,
) -> None:
    db.add(
        TaskProgressHistory(
            task_id=task.id,
            from_enabled=from_enabled,
            to_enabled=task.progress_enabled,
            from_percent=from_percent,
            to_percent=task.progress_percent,
            from_status=from_status,
            to_status=task.status,
            reason=reason,
            changed_by=actor.id,
        )
    )


def _complete_task(
    db: Session,
    task: Task,
    *,
    result: str,
    actor: User,
    cascade_root_id: str | None = None,
) -> None:
    before = jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS)
    from_enabled = task.progress_enabled
    from_percent = task.progress_percent
    from_status = task.status
    now = utc_now()
    task.status = TaskStatus.DONE.value
    task.result = result
    task.completed_at = now
    task.blocker_reason = None
    if task.progress_enabled:
        task.progress_percent = 100
    task.revision += 1
    task.updated_at = now
    if task.progress_enabled and (
        from_percent != task.progress_percent or from_status != task.status
    ):
        _record_progress_history(
            db,
            task=task,
            from_enabled=from_enabled,
            from_percent=from_percent,
            from_status=from_status,
            reason="completed_with_parent" if cascade_root_id else "task_completed",
            actor=actor,
        )
    record_audit(
        db,
        actor=actor,
        action="task.transition",
        entity_type="task",
        entity_id=task.id,
        before_data=before,
        after_data=jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS),
        detail={"cascadeRootId": cascade_root_id} if cascade_root_id else None,
    )


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
    if payload.complete_descendants and target != TaskStatus.DONE.value:
        raise AppError(
            "COMPLETE_DESCENDANTS_ONLY_FOR_DONE",
            "只有完成父任务时才能同步完成子任务",
        )
    if target == TaskStatus.BLOCKED.value and not payload.blocker_reason:
        raise AppError("BLOCKER_REASON_REQUIRED", "阻塞任务必须填写阻塞原因")
    if target == TaskStatus.DONE.value and not payload.result:
        raise AppError("TASK_RESULT_REQUIRED", "完成任务必须填写完成结果")
    if target == TaskStatus.CANCELLED.value and not payload.cancel_reason:
        raise AppError("TASK_CANCEL_REASON_REQUIRED", "取消任务必须填写取消原因")

    descendants: list[Task] = []
    if payload.complete_descendants:
        descendants = [
            descendant
            for descendant in _active_descendants(db, task)
            if descendant.status not in TERMINAL_TASK_STATUSES
        ]
        for descendant in descendants:
            require_manage_task(db, actor, descendant)

    if target == TaskStatus.DONE.value:
        assert payload.result is not None
        _complete_task(db, task, result=payload.result, actor=actor)
        for descendant in descendants:
            _complete_task(
                db,
                descendant,
                result=payload.result,
                actor=actor,
                cascade_root_id=task.id,
            )
        return task

    before = jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS)
    from_enabled = task.progress_enabled
    from_percent = task.progress_percent
    from_status = task.status
    task.status = target
    if target == TaskStatus.IN_PROGRESS.value:
        task.started_at = task.started_at or utc_now()
        task.blocker_reason = None
    elif target == TaskStatus.BLOCKED.value:
        task.blocker_reason = payload.blocker_reason
    elif target == TaskStatus.CANCELLED.value:
        task.cancel_reason = payload.cancel_reason
    task.revision += 1
    task.updated_at = utc_now()
    if task.progress_enabled and from_status != task.status:
        _record_progress_history(
            db,
            task=task,
            from_enabled=from_enabled,
            from_percent=from_percent,
            from_status=from_status,
            reason="task_status_transition",
            actor=actor,
        )
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


def update_task_progress(
    db: Session,
    task: Task,
    payload: TaskProgressUpdate,
    actor: User,
) -> Task:
    require_manage_task(db, actor, task)
    assert_revision(task, payload.revision, entity_name="task")
    if task.status == TaskStatus.CANCELLED.value:
        raise AppError("TASK_PROGRESS_TERMINAL", "已取消任务不能修改进度")

    from_enabled = task.progress_enabled
    from_percent = task.progress_percent
    from_status = task.status
    before = jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS)

    if not payload.enabled:
        task.progress_enabled = False
        task.progress_percent = None
    else:
        percent = payload.percent
        if percent is None:
            raise AppError("TASK_PROGRESS_REQUIRED", "开启进度跟踪时必须提供进度")
        if percent % 5:
            raise AppError("TASK_PROGRESS_STEP_INVALID", "任务进度必须按 5% 调整")
        if task.status == TaskStatus.DONE.value and percent != 100:
            raise AppError("TASK_PROGRESS_STATUS_MISMATCH", "已完成任务的进度必须为 100%")
        if percent == 100:
            result = payload.result or task.result
            if not result:
                raise AppError("TASK_RESULT_REQUIRED", "进度设为 100% 时必须填写完成结果")
            task.status = TaskStatus.DONE.value
            task.result = result
            task.completed_at = task.completed_at or utc_now()
            task.blocker_reason = None
        elif task.status == TaskStatus.DONE.value:
            raise AppError("TASK_PROGRESS_STATUS_MISMATCH", "已完成任务的进度不能低于 100%")
        elif task.status == TaskStatus.TODO.value and percent > 0:
            task.status = TaskStatus.IN_PROGRESS.value
            task.started_at = task.started_at or utc_now()
        task.progress_enabled = True
        task.progress_percent = percent

    if (
        from_enabled == task.progress_enabled
        and from_percent == task.progress_percent
        and from_status == task.status
    ):
        raise AppError("TASK_PROGRESS_UNCHANGED", "任务进度没有变化")

    task.revision += 1
    task.updated_at = utc_now()
    _record_progress_history(
        db,
        task=task,
        from_enabled=from_enabled,
        from_percent=from_percent,
        from_status=from_status,
        reason=payload.reason,
        actor=actor,
    )
    record_audit(
        db,
        actor=actor,
        action="task.progress.update",
        entity_type="task",
        entity_id=task.id,
        before_data=before,
        after_data=jsonable_snapshot(task, TASK_SNAPSHOT_FIELDS),
        detail={"reason": payload.reason},
    )
    return task


def list_task_progress_history(
    db: Session,
    task: Task,
    *,
    actor: User,
) -> list[TaskProgressHistory]:
    if not can_view_task(db, actor, task):
        raise NotFoundError("TASK_NOT_FOUND", "任务不存在")
    return list(
        db.scalars(
            select(TaskProgressHistory)
            .where(TaskProgressHistory.task_id == task.id)
            .order_by(
                TaskProgressHistory.changed_at.desc(),
                TaskProgressHistory.id.desc(),
            )
        ).all()
    )


def delete_task_tree(
    db: Session,
    task: Task,
    payload: TaskTreeDelete,
    actor: User,
) -> int:
    require_manage_task(db, actor, task)
    assert_revision(task, payload.revision, entity_name="task")
    descendants = _active_descendants(db, task)
    for descendant in descendants:
        require_manage_task(db, actor, descendant)

    now = utc_now()
    tree = [task, *descendants]
    for item in reversed(tree):
        before = jsonable_snapshot(item, TASK_SNAPSHOT_FIELDS)
        item.deleted_at = now
        item.deleted_by = actor.id
        item.revision += 1
        item.updated_at = now
        record_audit(
            db,
            actor=actor,
            action="task.delete",
            entity_type="task",
            entity_id=item.id,
            before_data=before,
            detail={
                "reason": payload.reason,
                "treeRootId": task.id,
                "treeSize": len(tree),
            },
        )
    return len(tree)


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
    owner = ensure_user(db, owner_id)
    _require_user_can_own_task_source(db, owner, task)
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
