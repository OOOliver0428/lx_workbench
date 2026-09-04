from __future__ import annotations

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import (
    is_super_admin,
    jsonable_snapshot,
    new_department_work_code,
    normalize_name,
)
from app.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import (
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    DepartmentWorkVisibility,
    Task,
    TaskStatus,
    User,
    UserRole,
    WorkRecord,
    utc_now,
)
from app.schemas import DepartmentWorkCreate, DepartmentWorkTransition, DepartmentWorkUpdate
from app.services.departments import (
    get_department,
    is_department_member,
    visible_department_ids,
)
from app.services.projects import assert_revision

DEPARTMENT_WORK_SNAPSHOT_FIELDS = (
    "id",
    "code",
    "name",
    "description",
    "department_id",
    "owner_id",
    "status",
    "visibility",
    "created_by",
    "revision",
)

DEPARTMENT_WORK_TRANSITIONS: dict[str, set[str]] = {
    DepartmentWorkStatus.IN_PROGRESS.value: {
        DepartmentWorkStatus.COMPLETED.value,
        DepartmentWorkStatus.ARCHIVED.value,
    },
    DepartmentWorkStatus.COMPLETED.value: {
        DepartmentWorkStatus.IN_PROGRESS.value,
        DepartmentWorkStatus.ARCHIVED.value,
    },
    DepartmentWorkStatus.ARCHIVED.value: set(),
}


def get_department_work(
    db: Session,
    department_work_id: str,
    *,
    include_deleted: bool = False,
) -> DepartmentWork:
    work = db.get(DepartmentWork, department_work_id)
    if not work or (work.deleted_at and not include_deleted):
        raise NotFoundError("DEPARTMENT_WORK_NOT_FOUND", "部门工作不存在")
    return work


def can_view_department_work(db: Session, user: User, work: DepartmentWork) -> bool:
    if user.role in {UserRole.SYSTEM_ADMIN.value, UserRole.SUPER_ADMIN.value}:
        return True
    if work.visibility == DepartmentWorkVisibility.PUBLIC.value:
        return True
    return work.department_id in visible_department_ids(db, user)


def require_view_department_work(db: Session, user: User, work: DepartmentWork) -> None:
    if not can_view_department_work(db, user, work):
        raise PermissionDeniedError("无权查看该部门工作")


def can_manage_department_work(db: Session, user: User, work: DepartmentWork) -> bool:
    """Return the entity-level management scope, independent of feature grants."""

    if is_super_admin(user):
        return True
    return bool(user.is_active and work.department_id in visible_department_ids(db, user))


def require_manage_department_work(db: Session, user: User, work: DepartmentWork) -> None:
    if not can_manage_department_work(db, user, work):
        raise PermissionDeniedError("只有负责部门成员或超级管理员可以修改部门工作")


def is_department_work_writable(work: DepartmentWork) -> bool:
    return work.status != DepartmentWorkStatus.ARCHIVED.value and not work.deleted_at


def require_department_work_writable(work: DepartmentWork) -> None:
    if not is_department_work_writable(work):
        raise ConflictError(
            "DEPARTMENT_WORK_ARCHIVED",
            "已归档部门工作为只读状态",
        )


def can_create_in_department(db: Session, user: User, department: Department) -> bool:
    """Scope guard; callers still enforce their operation-specific permission."""

    if not user.is_active or department.deleted_at or not department.is_active:
        return False
    return is_super_admin(user) or is_department_member(db, user, department)


def can_create_in_department_work(
    db: Session,
    user: User,
    work: DepartmentWork,
) -> bool:
    if work.deleted_at or work.status != DepartmentWorkStatus.IN_PROGRESS.value:
        return False
    department = db.get(Department, work.department_id)
    return bool(department and can_create_in_department(db, user, department))


def require_create_in_department(
    db: Session,
    user: User,
    department: Department,
) -> None:
    if not can_create_in_department(db, user, department):
        raise PermissionDeniedError("只能在自己的主部门或所负责部门中创建部门工作")


def require_create_in_department_work(
    db: Session,
    user: User,
    work: DepartmentWork,
) -> None:
    if work.status == DepartmentWorkStatus.COMPLETED.value:
        raise ConflictError(
            "DEPARTMENT_WORK_COMPLETED",
            "已完成的部门工作不能新建任务，请先重新开启",
        )
    if work.status == DepartmentWorkStatus.ARCHIVED.value:
        raise ConflictError(
            "DEPARTMENT_WORK_ARCHIVED",
            "已归档部门工作为只读状态",
        )
    if not can_create_in_department_work(db, user, work):
        raise PermissionDeniedError("只能在自己的主部门或所负责部门中创建任务")


def _ensure_name_available(
    db: Session,
    department_id: str,
    name: str,
    *,
    exclude_id: str | None = None,
) -> str:
    normalized = normalize_name(name)
    if not normalized:
        raise AppError("INVALID_DEPARTMENT_WORK_NAME", "部门工作名称不能只包含空格或符号")
    query = select(DepartmentWork.id).where(
        DepartmentWork.department_id == department_id,
        DepartmentWork.normalized_name == normalized,
        DepartmentWork.deleted_at.is_(None),
        DepartmentWork.status != DepartmentWorkStatus.ARCHIVED.value,
    )
    if exclude_id:
        query = query.where(DepartmentWork.id != exclude_id)
    if db.scalar(query.limit(1)):
        raise ConflictError(
            "DEPARTMENT_WORK_NAME_CONFLICT",
            "该部门已存在同名的未归档工作",
        )
    return normalized


def _ensure_owner(
    db: Session,
    owner_id: str,
    department_id: str,
) -> User:
    owner = db.get(User, owner_id)
    if (
        not owner
        or not owner.is_active
        or owner.role == UserRole.SUPER_ADMIN.value
        or department_id not in visible_department_ids(db, owner)
    ):
        raise AppError(
            "INVALID_DEPARTMENT_WORK_OWNER",
            "负责人必须是负责部门的有效成员或该部门负责人",
        )
    return owner


def list_department_works(
    db: Session,
    actor: User,
    *,
    department_id: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    query_text: str | None = None,
    include_archived: bool = False,
) -> list[DepartmentWork]:
    query = select(DepartmentWork).where(DepartmentWork.deleted_at.is_(None))
    if actor.role not in {UserRole.SYSTEM_ADMIN.value, UserRole.SUPER_ADMIN.value}:
        scope = [DepartmentWork.visibility == DepartmentWorkVisibility.PUBLIC.value]
        scoped_department_ids = visible_department_ids(db, actor)
        if scoped_department_ids:
            scope.append(DepartmentWork.department_id.in_(scoped_department_ids))
        query = query.where(or_(*scope))
    if department_id:
        query = query.where(DepartmentWork.department_id == department_id)
    if owner_id:
        query = query.where(DepartmentWork.owner_id == owner_id)
    if status:
        query = query.where(DepartmentWork.status == status)
    elif not include_archived:
        query = query.where(DepartmentWork.status != DepartmentWorkStatus.ARCHIVED.value)
    if visibility:
        query = query.where(DepartmentWork.visibility == visibility)
    if query_text:
        normalized = normalize_name(query_text)
        if normalized:
            query = query.where(DepartmentWork.normalized_name.contains(normalized))

    status_order = case(
        (DepartmentWork.status == DepartmentWorkStatus.IN_PROGRESS.value, 0),
        (DepartmentWork.status == DepartmentWorkStatus.COMPLETED.value, 1),
        else_=2,
    )
    return list(
        db.scalars(query.order_by(status_order, DepartmentWork.updated_at.desc()).limit(500)).all()
    )


def create_department_work(
    db: Session,
    payload: DepartmentWorkCreate,
    actor: User,
) -> DepartmentWork:
    department_id = payload.department_id or actor.primary_department_id
    if not department_id:
        raise AppError(
            "DEPARTMENT_REQUIRED",
            "未设置主部门时必须明确选择负责部门",
        )
    department = get_department(db, department_id)
    require_create_in_department(db, actor, department)
    owner_id = payload.owner_id or actor.id
    _ensure_owner(db, owner_id, department.id)
    normalized = _ensure_name_available(db, department.id, payload.name)
    work = DepartmentWork(
        code=new_department_work_code(),
        name=payload.name.strip(),
        normalized_name=normalized,
        description=payload.description.strip() if payload.description else None,
        department_id=department.id,
        owner_id=owner_id,
        status=DepartmentWorkStatus.IN_PROGRESS.value,
        visibility=payload.visibility.value,
        created_by=actor.id,
    )
    db.add(work)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="department_work.create",
        entity_type="department_work",
        entity_id=work.id,
        after_data=jsonable_snapshot(work, DEPARTMENT_WORK_SNAPSHOT_FIELDS),
    )
    return work


def update_department_work(
    db: Session,
    work: DepartmentWork,
    payload: DepartmentWorkUpdate,
    actor: User,
) -> DepartmentWork:
    require_manage_department_work(db, actor, work)
    require_department_work_writable(work)
    assert_revision(work, payload.revision, entity_name="department_work")
    fields = payload.model_fields_set - {"revision"}
    if not fields:
        raise AppError("DEPARTMENT_WORK_UPDATE_EMPTY", "请至少修改一项部门工作")

    before = jsonable_snapshot(work, DEPARTMENT_WORK_SNAPSHOT_FIELDS)
    if "name" in fields and payload.name:
        normalized = _ensure_name_available(
            db,
            work.department_id,
            payload.name,
            exclude_id=work.id,
        )
        work.name = payload.name.strip()
        work.normalized_name = normalized
    if "description" in fields:
        work.description = payload.description.strip() if payload.description else None
    if "owner_id" in fields and payload.owner_id:
        _ensure_owner(db, payload.owner_id, work.department_id)
        work.owner_id = payload.owner_id
    if "visibility" in fields and payload.visibility:
        work.visibility = payload.visibility.value

    work.revision += 1
    work.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="department_work.update",
        entity_type="department_work",
        entity_id=work.id,
        before_data=before,
        after_data=jsonable_snapshot(work, DEPARTMENT_WORK_SNAPSHOT_FIELDS),
    )
    return work


def transition_department_work(
    db: Session,
    work: DepartmentWork,
    payload: DepartmentWorkTransition,
    actor: User,
) -> DepartmentWork:
    require_manage_department_work(db, actor, work)
    require_department_work_writable(work)
    assert_revision(work, payload.revision, entity_name="department_work")
    target_status = payload.status.value
    if target_status not in DEPARTMENT_WORK_TRANSITIONS.get(work.status, set()):
        raise AppError(
            "INVALID_DEPARTMENT_WORK_TRANSITION",
            f"部门工作不能从 {work.status} 转为 {target_status}",
        )
    if target_status == DepartmentWorkStatus.ARCHIVED.value:
        unfinished_task_count = int(
            db.scalar(
                select(func.count(Task.id)).where(
                    Task.department_work_id == work.id,
                    Task.deleted_at.is_(None),
                    Task.status.not_in(
                        {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}
                    ),
                )
            )
            or 0
        )
        if unfinished_task_count:
            raise ConflictError(
                "DEPARTMENT_WORK_ACTIVE_TASKS",
                "仍有未完成任务，全部完成或取消后才能归档部门工作",
                {"unfinished_task_count": unfinished_task_count},
            )

    before = jsonable_snapshot(work, DEPARTMENT_WORK_SNAPSHOT_FIELDS)
    work.status = target_status
    work.revision += 1
    work.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="department_work.transition",
        entity_type="department_work",
        entity_id=work.id,
        before_data=before,
        after_data=jsonable_snapshot(work, DEPARTMENT_WORK_SNAPSHOT_FIELDS),
    )
    return work


def _linked_entity_counts(db: Session, work: DepartmentWork) -> tuple[int, int]:
    task_count = int(
        db.scalar(
            select(func.count(Task.id)).where(
                Task.department_work_id == work.id,
                Task.deleted_at.is_(None),
            )
        )
        or 0
    )
    record_count = int(
        db.scalar(
            select(func.count(WorkRecord.id)).where(
                WorkRecord.department_work_id == work.id,
                WorkRecord.deleted_at.is_(None),
            )
        )
        or 0
    )
    return task_count, record_count


def delete_department_work(
    db: Session,
    work: DepartmentWork,
    *,
    revision: int,
    reason: str | None,
    actor: User,
) -> None:
    require_manage_department_work(db, actor, work)
    require_department_work_writable(work)
    assert_revision(work, revision, entity_name="department_work")
    task_count, record_count = _linked_entity_counts(db, work)
    if task_count or record_count:
        raise ConflictError(
            "DEPARTMENT_WORK_IN_USE",
            "部门工作仍有关联任务或工作记录，不能删除",
            {"task_count": task_count, "work_record_count": record_count},
        )

    before = jsonable_snapshot(work, DEPARTMENT_WORK_SNAPSHOT_FIELDS)
    now = utc_now()
    work.deleted_at = now
    work.deleted_by = actor.id
    work.revision += 1
    work.updated_at = now
    record_audit(
        db,
        actor=actor,
        action="department_work.delete",
        entity_type="department_work",
        entity_id=work.id,
        before_data=before,
        detail={"reason": reason},
    )


# Compact aliases for callers that work with both project and department-work sources.
can_view = can_view_department_work
can_manage = can_manage_department_work
can_create_in = can_create_in_department_work
