from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import jsonable_snapshot, normalize_name
from app.errors import AppError, ConflictError, NotFoundError
from app.models import (
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    User,
    UserRole,
    utc_now,
)
from app.schemas import DepartmentCreate, DepartmentUpdate
from app.services.projects import assert_revision

DEPARTMENT_SNAPSHOT_FIELDS = (
    "id",
    "name",
    "leader_id",
    "is_active",
    "created_by",
    "revision",
)


def get_department(
    db: Session,
    department_id: str,
    *,
    include_deleted: bool = False,
) -> Department:
    department = db.get(Department, department_id)
    if not department or (department.deleted_at and not include_deleted):
        raise NotFoundError("DEPARTMENT_NOT_FOUND", "部门不存在")
    return department


def list_departments(
    db: Session,
    *,
    include_inactive: bool = False,
    query_text: str | None = None,
) -> list[Department]:
    query = select(Department).where(Department.deleted_at.is_(None))
    if not include_inactive:
        query = query.where(Department.is_active.is_(True))
    if query_text:
        normalized = normalize_name(query_text)
        if normalized:
            query = query.where(Department.normalized_name.contains(normalized))
    return list(
        db.scalars(query.order_by(Department.is_active.desc(), Department.name).limit(500)).all()
    )


def _ensure_name_available(
    db: Session,
    name: str,
    *,
    exclude_id: str | None = None,
) -> str:
    normalized = normalize_name(name)
    if not normalized:
        raise AppError("INVALID_DEPARTMENT_NAME", "部门名称不能只包含空格或符号")
    query = select(Department.id).where(
        Department.normalized_name == normalized,
        Department.deleted_at.is_(None),
    )
    if exclude_id:
        query = query.where(Department.id != exclude_id)
    if db.scalar(query.limit(1)):
        raise ConflictError("DEPARTMENT_NAME_CONFLICT", "已存在同名部门")
    return normalized


def _ensure_valid_leader(
    db: Session,
    department: Department,
    leader_id: str,
) -> User:
    """A department leader must be an active, assignable user.

    They do not need ``primary_department_id == department.id``: the same user
    may lead multiple departments while keeping a single primary department.
    """

    if department.deleted_at:
        raise NotFoundError("DEPARTMENT_NOT_FOUND", "部门不存在")
    leader = db.get(User, leader_id)
    if (
        not leader
        or not leader.is_active
        or leader.role == UserRole.SUPER_ADMIN.value
    ):
        raise AppError(
            "INVALID_DEPARTMENT_LEADER",
            "部门负责人必须是有效且可用的用户",
        )
    return leader


def create_department(
    db: Session,
    payload: DepartmentCreate,
    actor: User,
) -> Department:
    normalized = _ensure_name_available(db, payload.name)
    department = Department(
        name=payload.name.strip(),
        normalized_name=normalized,
        leader_id=None,
        is_active=True,
        created_by=actor.id,
    )
    db.add(department)
    db.flush()
    if payload.leader_id:
        leader = _ensure_valid_leader(db, department, payload.leader_id)
        department.leader_id = leader.id
        # Only fill in a missing primary department. Never rewrite an existing
        # one just to appoint the user as this department's leader.
        if leader.primary_department_id is None:
            user_before = {
                "primaryDepartmentId": leader.primary_department_id,
                "revision": leader.revision,
            }
            leader.primary_department_id = department.id
            leader.revision += 1
            leader.updated_at = utc_now()
            record_audit(
                db,
                actor=actor,
                action="user.department.assign",
                entity_type="user",
                entity_id=leader.id,
                before_data=user_before,
                after_data={
                    "primaryDepartmentId": department.id,
                    "revision": leader.revision,
                },
                detail={"reason": "initial_department_leader"},
            )
    # Initial leader assignment happens after the insert because it needs the
    # generated department ID. Flush the resulting versioned UPDATE so both
    # the audit snapshot and API response carry the current revision.
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="department.create",
        entity_type="department",
        entity_id=department.id,
        after_data=jsonable_snapshot(department, DEPARTMENT_SNAPSHOT_FIELDS),
    )
    return department


def update_department(
    db: Session,
    department: Department,
    payload: DepartmentUpdate,
    actor: User,
) -> Department:
    assert_revision(department, payload.revision, entity_name="department")
    fields = payload.model_fields_set - {"revision"}
    if not fields:
        raise AppError("DEPARTMENT_UPDATE_EMPTY", "请至少修改一项部门资料")

    before = jsonable_snapshot(department, DEPARTMENT_SNAPSHOT_FIELDS)
    if "name" in fields and payload.name:
        normalized = _ensure_name_available(
            db,
            payload.name,
            exclude_id=department.id,
        )
        department.name = payload.name.strip()
        department.normalized_name = normalized
    if "leader_id" in fields:
        if payload.leader_id:
            _ensure_valid_leader(db, department, payload.leader_id)
        department.leader_id = payload.leader_id
    if "is_active" in fields and payload.is_active is not None:
        if department.is_active and not payload.is_active:
            assigned_user_count = int(
                db.scalar(
                    select(func.count(User.id)).where(
                        User.primary_department_id == department.id
                    )
                )
                or 0
            )
            open_work_count = int(
                db.scalar(
                    select(func.count(DepartmentWork.id)).where(
                        DepartmentWork.department_id == department.id,
                        DepartmentWork.deleted_at.is_(None),
                        DepartmentWork.status != DepartmentWorkStatus.ARCHIVED.value,
                    )
                )
                or 0
            )
            if assigned_user_count or open_work_count:
                raise ConflictError(
                    "DEPARTMENT_DEACTIVATION_BLOCKED",
                    "部门仍有成员或未归档工作，请先完成迁移后再停用",
                    {
                        "assigned_user_count": assigned_user_count,
                        "open_department_work_count": open_work_count,
                    },
                )
        department.is_active = payload.is_active

    department.revision += 1
    department.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="department.update",
        entity_type="department",
        entity_id=department.id,
        before_data=before,
        after_data=jsonable_snapshot(department, DEPARTMENT_SNAPSHOT_FIELDS),
    )
    return department


def delete_department(
    db: Session,
    department: Department,
    *,
    revision: int,
    reason: str | None,
    actor: User,
) -> None:
    assert_revision(department, revision, entity_name="department")
    assigned_user_count = (
        db.scalar(select(func.count(User.id)).where(User.primary_department_id == department.id))
        or 0
    )
    department_work_count = (
        db.scalar(
            select(func.count(DepartmentWork.id)).where(
                DepartmentWork.department_id == department.id,
                DepartmentWork.deleted_at.is_(None),
            )
        )
        or 0
    )
    if assigned_user_count or department_work_count:
        raise ConflictError(
            "DEPARTMENT_IN_USE",
            "部门仍有关联成员或部门工作，不能删除",
            {
                "assigned_user_count": assigned_user_count,
                "department_work_count": department_work_count,
            },
        )

    before = jsonable_snapshot(department, DEPARTMENT_SNAPSHOT_FIELDS)
    now = utc_now()
    department.deleted_at = now
    department.deleted_by = actor.id
    department.is_active = False
    department.revision += 1
    department.updated_at = now
    record_audit(
        db,
        actor=actor,
        action="department.delete",
        entity_type="department",
        entity_id=department.id,
        before_data=before,
        detail={"reason": reason},
    )


def department_member_count(db: Session, department_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(User.id)).where(
                User.primary_department_id == department_id,
                User.is_active.is_(True),
                User.role != UserRole.SUPER_ADMIN.value,
            )
        )
        or 0
    )


def led_active_department_ids(db: Session, user_id: str) -> list[str]:
    """Return active, non-deleted departments the user currently leads."""

    return list(
        db.scalars(
            select(Department.id).where(
                Department.leader_id == user_id,
                Department.deleted_at.is_(None),
                Department.is_active.is_(True),
            )
        ).all()
    )


def visible_department_ids(db: Session, user: User) -> set[str]:
    """Departments the user can act in as a member-equivalent.

    Union of the single primary department (if any) and active departments
    they lead. This is not a membership M2M and does not change
    ``User.leader_id`` reporting lines.
    """

    ids = set(led_active_department_ids(db, user.id))
    if user.primary_department_id:
        ids.add(user.primary_department_id)
    return ids


def is_department_member(
    db: Session,
    user: User,
    department: Department | str,
) -> bool:
    """Member-equivalent scope: primary department or an actively led department.

    Users still have at most one ``primary_department_id``. Leading extra
    departments grants the same view/write/create/own scope as membership,
    without introducing a membership table.
    """

    if not user.is_active:
        return False
    department_id = department.id if isinstance(department, Department) else department
    return department_id in visible_department_ids(db, user)


def can_manage_department(actor: User) -> bool:
    """Entity-level guard used in addition to the DEPARTMENTS_MANAGE permission."""

    return actor.role in {
        UserRole.SYSTEM_ADMIN.value,
        UserRole.SUPER_ADMIN.value,
    }


def require_manage_department(actor: User) -> None:
    if not can_manage_department(actor):
        # A custom permission can be assigned only to supported administrators,
        # but retain this service-layer boundary for non-HTTP callers.
        raise AppError(
            "DEPARTMENT_MANAGEMENT_FORBIDDEN",
            "只有系统管理员可以维护部门主数据",
            status_code=403,
        )
