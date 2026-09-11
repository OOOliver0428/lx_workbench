from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import PermissionKey, User, UserRole
from app.schemas import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentPersonOut,
    DepartmentUpdate,
    RevisionAction,
)
from app.services import departments as department_service
from app.services import permissions as permission_service

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=list[DepartmentOut])
def list_departments(
    include_inactive: bool = False,
    q: str | None = Query(default=None, max_length=120),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[DepartmentOut]:
    permission_service.assert_permission(db, actor, PermissionKey.DEPARTMENTS_VIEW)
    return [
        DepartmentOut.model_validate(department)
        for department in department_service.list_departments(
            db,
            include_inactive=include_inactive,
            query_text=q,
        )
    ]


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(
    payload: DepartmentCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> DepartmentOut:
    permission_service.assert_permission(db, actor, PermissionKey.DEPARTMENTS_MANAGE)
    return DepartmentOut.model_validate(department_service.create_department(db, payload, actor))


@router.get("/personnel", response_model=list[DepartmentPersonOut])
def list_department_personnel(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[DepartmentPersonOut]:
    permission_service.assert_permission(db, actor, PermissionKey.DEPARTMENTS_VIEW)
    users = db.scalars(
        select(User).where(User.role != UserRole.SUPER_ADMIN.value).order_by(User.display_name)
    ).all()
    return [DepartmentPersonOut.model_validate(user) for user in users]


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(
    department_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> DepartmentOut:
    permission_service.assert_permission(db, actor, PermissionKey.DEPARTMENTS_VIEW)
    return DepartmentOut.model_validate(department_service.get_department(db, department_id))


@router.patch("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: str,
    payload: DepartmentUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> DepartmentOut:
    permission_service.assert_permission(db, actor, PermissionKey.DEPARTMENTS_MANAGE)
    department = department_service.get_department(db, department_id)
    return DepartmentOut.model_validate(
        department_service.update_department(db, department, payload, actor)
    )


@router.delete("/{department_id}", status_code=204)
def delete_department(
    department_id: str,
    payload: RevisionAction,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    permission_service.assert_permission(db, actor, PermissionKey.DEPARTMENTS_MANAGE)
    department_service.delete_department(
        db,
        department_service.get_department(db, department_id),
        revision=payload.revision,
        reason=payload.reason,
        actor=actor,
    )
