from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import PermissionKey, User
from app.schemas import (
    TaskCreate,
    TaskOut,
    TaskProgressHistoryOut,
    TaskProgressUpdate,
    TaskReassign,
    TaskRelationCreate,
    TaskRelationOut,
    TaskTimeScope,
    TaskTransition,
    TaskTreeDelete,
    TaskUpdate,
)
from app.serializers import task_out
from app.services import dashboard as dashboard_service
from app.services import permissions as permission_service
from app.services import tasks as task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    project_id: str | None = None,
    project_ids: list[str] | None = Query(default=None),
    department_work_id: str | None = None,
    department_work_ids: list[str] | None = Query(default=None),
    owner_id: str | None = None,
    status: str | None = None,
    time_scope: TaskTimeScope = TaskTimeScope.WEEK,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[TaskOut]:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_VIEW)
    return [
        task_out(db, task)
        for task in task_service.list_tasks(
            db,
            actor=actor,
            project_id=project_id,
            project_ids=project_ids,
            department_work_ids=[
                *([] if department_work_ids is None else department_work_ids),
                *([] if department_work_id is None else [department_work_id]),
            ],
            owner_id=owner_id,
            status=status,
            time_scope=time_scope,
        )
    ]


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> TaskOut:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_CREATE)
    return task_out(db, task_service.create_task(db, payload, actor))


@router.post("/relations", response_model=TaskRelationOut, status_code=201)
def create_task_relation(
    payload: TaskRelationCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> TaskRelationOut:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_EDIT)
    relation = dashboard_service.create_task_relation(db, payload, actor)
    return TaskRelationOut.model_validate(relation)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> TaskOut:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_VIEW)
    return task_out(db, task_service.get_task(db, task_id, actor=actor))


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> TaskOut:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_EDIT)
    task = task_service.get_task(db, task_id, actor=actor)
    return task_out(db, task_service.update_task(db, task, payload, actor))


@router.post("/{task_id}/transition", response_model=TaskOut)
def transition_task(
    task_id: str,
    payload: TaskTransition,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> TaskOut:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_EDIT)
    task = task_service.get_task(db, task_id, actor=actor)
    return task_out(db, task_service.transition_task(db, task, payload, actor))


@router.post("/{task_id}/reassign", response_model=TaskOut)
def reassign_task(
    task_id: str,
    payload: TaskReassign,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> TaskOut:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_EDIT)
    task = task_service.get_task(db, task_id, actor=actor)
    return task_out(
        db,
        task_service.reassign_task(
            db,
            task,
            owner_id=payload.owner_id,
            revision=payload.revision,
            reason=payload.reason,
            actor=actor,
        ),
    )


@router.patch("/{task_id}/progress", response_model=TaskOut)
def update_task_progress(
    task_id: str,
    payload: TaskProgressUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> TaskOut:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_EDIT)
    task = task_service.get_task(db, task_id, actor=actor)
    return task_out(db, task_service.update_task_progress(db, task, payload, actor))


@router.get(
    "/{task_id}/progress-history",
    response_model=list[TaskProgressHistoryOut],
)
def list_task_progress_history(
    task_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[TaskProgressHistoryOut]:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_VIEW)
    task = task_service.get_task(db, task_id, actor=actor)
    return [
        TaskProgressHistoryOut.model_validate(history)
        for history in task_service.list_task_progress_history(
            db,
            task,
            actor=actor,
        )
    ]


@router.delete("/{task_id}", status_code=204)
def delete_task_tree(
    task_id: str,
    payload: TaskTreeDelete,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> Response:
    permission_service.assert_permission(db, actor, PermissionKey.TASKS_EDIT)
    task = task_service.get_task(db, task_id, actor=actor)
    task_service.delete_task_tree(db, task, payload, actor)
    return Response(status_code=204)
