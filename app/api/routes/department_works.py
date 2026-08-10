from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import (
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    DepartmentWorkVisibility,
    PermissionKey,
    User,
)
from app.schemas import (
    DepartmentWorkCreate,
    DepartmentWorkOut,
    DepartmentWorkTransition,
    DepartmentWorkUpdate,
    RevisionAction,
)
from app.services import department_works as department_work_service
from app.services import permissions as permission_service

router = APIRouter(prefix="/department-works", tags=["department-works"])


def _department_work_out(db: Session, work: DepartmentWork) -> DepartmentWorkOut:
    db.flush()
    payload = DepartmentWorkOut.model_validate(work)
    department = db.get(Department, work.department_id)
    owner = db.get(User, work.owner_id)
    payload.department_name = department.name if department else "未知部门"
    payload.owner_display_name = owner.display_name if owner else "未知用户"
    return payload


@router.get("", response_model=list[DepartmentWorkOut])
def list_department_works(
    department_id: str | None = None,
    owner_id: str | None = None,
    status: DepartmentWorkStatus | None = None,
    visibility: DepartmentWorkVisibility | None = None,
    q: str | None = Query(default=None, max_length=200),
    include_archived: bool = False,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[DepartmentWorkOut]:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DEPARTMENT_WORKS_VIEW,
    )
    rows = department_work_service.list_department_works(
        db,
        actor,
        department_id=department_id,
        owner_id=owner_id,
        status=status.value if status else None,
        visibility=visibility.value if visibility else None,
        query_text=q,
        include_archived=include_archived,
    )
    return [_department_work_out(db, work) for work in rows]


@router.post("", response_model=DepartmentWorkOut, status_code=201)
def create_department_work(
    payload: DepartmentWorkCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> DepartmentWorkOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DEPARTMENT_WORKS_CREATE,
    )
    return _department_work_out(
        db,
        department_work_service.create_department_work(db, payload, actor),
    )


@router.get("/{department_work_id}", response_model=DepartmentWorkOut)
def get_department_work(
    department_work_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> DepartmentWorkOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DEPARTMENT_WORKS_VIEW,
    )
    work = department_work_service.get_department_work(db, department_work_id)
    department_work_service.require_view_department_work(db, actor, work)
    return _department_work_out(db, work)


@router.patch("/{department_work_id}", response_model=DepartmentWorkOut)
def update_department_work(
    department_work_id: str,
    payload: DepartmentWorkUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> DepartmentWorkOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DEPARTMENT_WORKS_EDIT,
    )
    work = department_work_service.get_department_work(db, department_work_id)
    return _department_work_out(
        db,
        department_work_service.update_department_work(db, work, payload, actor),
    )


@router.post("/{department_work_id}/transition", response_model=DepartmentWorkOut)
def transition_department_work(
    department_work_id: str,
    payload: DepartmentWorkTransition,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> DepartmentWorkOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DEPARTMENT_WORKS_EDIT,
    )
    work = department_work_service.get_department_work(db, department_work_id)
    return _department_work_out(
        db,
        department_work_service.transition_department_work(db, work, payload, actor),
    )


@router.delete("/{department_work_id}", status_code=204)
def delete_department_work(
    department_work_id: str,
    payload: RevisionAction,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DEPARTMENT_WORKS_EDIT,
    )
    department_work_service.delete_department_work(
        db,
        department_work_service.get_department_work(db, department_work_id),
        revision=payload.revision,
        reason=payload.reason,
        actor=actor,
    )
