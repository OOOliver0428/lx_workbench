from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import User
from app.schemas import TaskCreate, TaskOut, TaskReassign, TaskTransition, TaskUpdate
from app.serializers import task_out
from app.services import tasks as task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    project_id: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    _actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    return [
        task_out(db, task)
        for task in task_service.list_tasks(
            db,
            project_id=project_id,
            owner_id=owner_id,
            status=status,
        )
    ]


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TaskOut:
    return task_out(db, task_service.create_task(db, payload, actor))


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    _actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    return task_out(db, task_service.get_task(db, task_id))


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = task_service.get_task(db, task_id)
    return task_out(db, task_service.update_task(db, task, payload, actor))


@router.post("/{task_id}/transition", response_model=TaskOut)
def transition_task(
    task_id: str,
    payload: TaskTransition,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = task_service.get_task(db, task_id)
    return task_out(db, task_service.transition_task(db, task, payload, actor))


@router.post("/{task_id}/reassign", response_model=TaskOut)
def reassign_task(
    task_id: str,
    payload: TaskReassign,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = task_service.get_task(db, task_id)
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
