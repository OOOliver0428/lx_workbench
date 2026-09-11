import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.dependencies import get_current_user, get_db, require_csrf
from app.domain import DIRECT_LEADER_ROLES, can_be_direct_leader, is_super_admin
from app.errors import AppError, ConflictError, NotFoundError
from app.identity import normalize_user_identifier
from app.models import (
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    PermissionKey,
    Task,
    TaskStatus,
    User,
    UserRole,
    utc_now,
)
from app.schemas import (
    PermissionDefinitionOut,
    UserCandidateOut,
    UserCreate,
    UserLeaderUpdate,
    UserOut,
    UserPermissionsOut,
    UserPermissionsUpdate,
    UserUpdate,
)
from app.security import hash_password, verify_password
from app.services import permissions as permission_service
from app.services.departments import led_active_department_ids
from app.throttle import LoginCapacityExceeded

router = APIRouter(prefix="/users", tags=["users"])


def _generate_login_name(db: Session) -> str:
    for _attempt in range(20):
        login_name = f"u{secrets.randbelow(100_000_000):08d}"
        if not db.scalar(
            select(User.id).where(
                or_(
                    User.login_name == login_name,
                    User.display_name_key == login_name,
                )
            )
        ):
            return login_name
    raise AppError(
        "LOGIN_NAME_GENERATION_FAILED",
        "暂时无法生成登录名，请重试",
        status_code=503,
    )


def _assert_display_name_available(
    db: Session,
    display_name: str,
    *,
    exclude_user_id: str | None = None,
) -> None:
    display_name_key = normalize_user_identifier(display_name)
    query = select(User.id).where(
        or_(
            User.display_name_key == display_name_key,
            User.login_name == display_name_key,
        )
    )
    if exclude_user_id:
        query = query.where(User.id != exclude_user_id)
    if db.scalar(query.limit(1)):
        raise ConflictError(
            "DISPLAY_NAME_ALREADY_EXISTS",
            "显示名称已被使用，请换一个",
        )


def _get_assignable_leader(db: Session, leader_id: str) -> User:
    leader = db.get(User, leader_id)
    if not leader or not can_be_direct_leader(leader):
        raise AppError(
            "DIRECT_LEADER_INVALID",
            "直属 Leader 必须是有效的团队负责人或系统管理员账号",
        )
    return leader


def _get_active_department(db: Session, department_id: str) -> Department:
    department = db.get(Department, department_id)
    if not department or department.deleted_at or not department.is_active:
        raise AppError("DEPARTMENT_INVALID", "主部门必须是有效部门")
    return department


def _ensure_no_leader_cycle(db: Session, user: User, leader: User) -> None:
    current: User | None = leader
    visited: set[str] = set()
    while current and current.id not in visited:
        if current.id == user.id:
            raise AppError("DIRECT_LEADER_CYCLE", "直属 Leader 关系不能形成管理环")
        visited.add(current.id)
        current = db.get(User, current.leader_id) if current.leader_id else None


def _ensure_department_change_safe(
    db: Session,
    user: User,
    target_department_id: str | None,
) -> None:
    if target_department_id == user.primary_department_id:
        return
    blocking_department_ids = [
        department_id
        for department_id in led_active_department_ids(db, user.id)
        if department_id != target_department_id
    ]
    if blocking_department_ids:
        raise ConflictError(
            "DEPARTMENT_LEADER_REASSIGN_REQUIRED",
            "该用户仍是部门负责人，请先调整部门负责人后再变更主部门",
            {
                "department_ids": blocking_department_ids,
                "department_id": blocking_department_ids[0],
            },
        )
    owned_work = db.scalar(
        select(DepartmentWork).where(
            DepartmentWork.owner_id == user.id,
            DepartmentWork.deleted_at.is_(None),
            DepartmentWork.status != DepartmentWorkStatus.ARCHIVED.value,
            DepartmentWork.department_id != target_department_id,
        )
    )
    if owned_work:
        raise ConflictError(
            "DEPARTMENT_WORK_OWNER_REASSIGN_REQUIRED",
            "该用户仍负责未归档的部门工作，请先改派后再变更主部门",
            {"department_work_id": owned_work.id},
        )
    owned_task = db.scalar(
        select(Task)
        .join(DepartmentWork, DepartmentWork.id == Task.department_work_id)
        .where(
            Task.owner_id == user.id,
            Task.deleted_at.is_(None),
            Task.status.not_in({TaskStatus.DONE.value, TaskStatus.CANCELLED.value}),
            DepartmentWork.deleted_at.is_(None),
            DepartmentWork.status != DepartmentWorkStatus.ARCHIVED.value,
            DepartmentWork.department_id != target_department_id,
        )
    )
    if owned_task:
        raise ConflictError(
            "DEPARTMENT_TASK_OWNER_REASSIGN_REQUIRED",
            "该用户仍负责原部门的未完成任务，请先改派后再变更主部门",
            {"task_id": owned_task.id},
        )


@router.get("", response_model=list[UserOut])
def list_users(
    include_inactive: bool = False,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[UserOut]:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.USERS_MANAGE,
    )
    query = select(User)
    if not include_inactive:
        query = query.where(User.is_active.is_(True))
    users = db.scalars(query.order_by(User.display_name)).all()
    return [
        UserOut.model_validate(user) for user in users if user.role != UserRole.SUPER_ADMIN.value
    ]


@router.get("/candidates", response_model=list[UserCandidateOut])
def list_user_candidates(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[UserCandidateOut]:
    permission_service.assert_any_permission(
        db,
        actor,
        (
            PermissionKey.PROJECTS_VIEW,
            PermissionKey.TASKS_VIEW,
            PermissionKey.DASHBOARD_OPPORTUNITY_CREATE,
        ),
        "当前账号无权查看负责人候选目录",
    )
    users = db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.display_name)
    ).all()
    return [
        UserCandidateOut.model_validate(user)
        for user in users
        if user.role != UserRole.SUPER_ADMIN.value
    ]


@router.get("/permissions/catalog", response_model=list[PermissionDefinitionOut])
def permission_catalog(
    actor: User = Depends(get_current_user),
) -> list[PermissionDefinitionOut]:
    permission_service.assert_permission_manager(actor)
    return [
        PermissionDefinitionOut(
            key=definition.key.value,
            group=definition.group,
            group_label=definition.group_label,
            label=definition.label,
            description=definition.description,
            system_admin_assignable=definition.system_admin_assignable,
            requires_team_scope=definition.requires_team_scope,
        )
        for definition in permission_service.PERMISSION_CATALOG
    ]


@router.get("/{user_id}/permissions", response_model=UserPermissionsOut)
def get_user_permissions(
    user_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> UserPermissionsOut:
    target = db.get(User, user_id)
    if not target or target.role == UserRole.SUPER_ADMIN.value:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    permission_service.assert_permission_manager(actor)
    if not is_super_admin(actor) and target.role not in {
        UserRole.MEMBER.value,
        UserRole.TEAM_LEADER.value,
    }:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    assigned = permission_service.assigned_permission_keys(db, target.id)
    return UserPermissionsOut(
        user_id=target.id,
        revision=target.revision,
        assigned_permissions=[
            key for key in permission_service.ALL_PERMISSION_KEYS if key in assigned
        ],
        effective_permissions=permission_service.effective_permission_keys(db, target),
    )


@router.put("/{user_id}/permissions", response_model=UserPermissionsOut)
def update_user_permissions(
    user_id: str,
    payload: UserPermissionsUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> UserPermissionsOut:
    target = db.get(User, user_id)
    if not target or target.role == UserRole.SUPER_ADMIN.value:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    assigned = permission_service.replace_user_permissions(
        db,
        actor=actor,
        target=target,
        expected_revision=payload.revision,
        requested_keys={permission.value for permission in payload.permissions},
    )
    return UserPermissionsOut(
        user_id=target.id,
        revision=target.revision,
        assigned_permissions=assigned,
        effective_permissions=permission_service.effective_permission_keys(db, target),
    )


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> UserOut:
    permission_service.assert_permission(db, actor, PermissionKey.USERS_MANAGE)
    if payload.role == UserRole.SUPER_ADMIN:
        raise AppError("SUPER_ADMIN_API_FORBIDDEN", "超级管理员只能通过服务器命令创建")
    if payload.role == UserRole.SYSTEM_ADMIN and not is_super_admin(actor):
        raise AppError(
            "SYSTEM_ADMIN_ROLE_FORBIDDEN",
            "只有超级管理员可以创建系统管理员",
            status_code=403,
        )
    _assert_display_name_available(db, payload.display_name)
    login_name = _generate_login_name(db)
    user = User(
        login_name=login_name,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=payload.role.value,
        leader_id=None,
        primary_department_id=(
            _get_active_department(db, payload.primary_department_id).id
            if payload.primary_department_id
            else None
        ),
        must_change_password=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as error:
        raise ConflictError(
            "DISPLAY_NAME_ALREADY_EXISTS",
            "显示名称已被使用，请换一个",
        ) from error
    initial_permissions = permission_service.grant_initial_permissions(
        db,
        user=user,
        actor=actor,
    )
    record_audit(
        db,
        actor=actor,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        after_data={
            "loginName": user.login_name,
            "displayName": user.display_name,
            "role": user.role,
            "leaderId": None,
            "primaryDepartmentId": user.primary_department_id,
            "permissions": initial_permissions,
        },
    )
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> UserOut:
    permission_service.assert_permission(db, actor, PermissionKey.USERS_MANAGE)
    user = db.get(User, user_id)
    if not user or user.role == UserRole.SUPER_ADMIN.value:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    if user.role == UserRole.SYSTEM_ADMIN.value and not is_super_admin(actor):
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    if payload.revision != user.revision:
        raise ConflictError(
            "REVISION_CONFLICT",
            "用户资料已被其他管理员修改，请刷新后重试",
            {
                "expected_revision": payload.revision,
                "current_revision": user.revision,
            },
        )

    fields = payload.model_fields_set - {"revision", "current_password"}
    if not fields:
        raise AppError("USER_UPDATE_EMPTY", "请至少修改一项用户资料")
    before_data = {
        "displayName": user.display_name,
        "role": user.role,
        "leaderId": user.leader_id,
        "primaryDepartmentId": user.primary_department_id,
        "isActive": user.is_active,
        "revision": user.revision,
    }
    if "is_active" in fields and payload.is_active is not None:
        password_matches = False
        if payload.current_password:
            try:
                with request.app.state.login_throttle.verification_slot(
                    request.client.host if request.client else "unknown"
                ):
                    password_matches = verify_password(
                        actor.password_hash, payload.current_password
                    )
            except LoginCapacityExceeded as exc:
                raise AppError(
                    "PASSWORD_VERIFICATION_LIMITED",
                    "密码验证过于频繁，请稍后重试",
                    status_code=429,
                ) from exc
        if not password_matches:
            raise AppError(
                "INVALID_CURRENT_PASSWORD",
                "请输入当前登录账号的正确密码，才能冻结或解冻账号",
                status_code=400,
            )
        if payload.is_active == user.is_active:
            pass
        else:
            if actor.id == user.id:
                raise AppError(
                    "SELF_FREEZE_FORBIDDEN",
                    "不能冻结或解冻自己的账号",
                    status_code=403,
                )
            if user.role == UserRole.SYSTEM_ADMIN.value and not is_super_admin(actor):
                raise AppError(
                    "SYSTEM_ADMIN_FREEZE_FORBIDDEN",
                    "只有超级管理员可以冻结系统管理员账号",
                    status_code=403,
                )
            if not payload.is_active and db.scalar(
                select(User.id).where(User.leader_id == user.id, User.is_active.is_(True)).limit(1)
            ):
                raise ConflictError(
                    "LEADER_HAS_DIRECT_REPORTS",
                    "该用户仍有在职直属成员，请先调整直属 Leader 后再冻结",
                )
            user.is_active = payload.is_active
    if "role" in fields and payload.role:
        if payload.role == UserRole.SUPER_ADMIN:
            raise AppError(
                "SUPER_ADMIN_API_FORBIDDEN",
                "超级管理员角色只能通过服务器命令管理",
            )
        if (
            payload.role == UserRole.SYSTEM_ADMIN or user.role == UserRole.SYSTEM_ADMIN.value
        ) and not is_super_admin(actor):
            raise AppError(
                "SYSTEM_ADMIN_ROLE_FORBIDDEN",
                "只有超级管理员可以调整系统管理员角色",
                status_code=403,
            )
        if actor.id == user.id and payload.role.value != user.role:
            raise AppError(
                "SELF_ROLE_CHANGE_FORBIDDEN",
                "不能修改自己的系统角色",
            )
        if (
            user.role in DIRECT_LEADER_ROLES
            and payload.role.value not in DIRECT_LEADER_ROLES
            and db.scalar(select(User.id).where(User.leader_id == user.id).limit(1))
        ):
            raise ConflictError(
                "LEADER_HAS_DIRECT_REPORTS",
                "该团队负责人仍有直属成员，请先调整这些成员的直属 Leader",
            )
        user.role = payload.role.value
    if "display_name" in fields and payload.display_name:
        _assert_display_name_available(
            db,
            payload.display_name,
            exclude_user_id=user.id,
        )
        user.display_name = payload.display_name
    if "leader_id" in fields:
        if payload.leader_id:
            leader = _get_assignable_leader(db, payload.leader_id)
            _ensure_no_leader_cycle(db, user, leader)
            user.leader_id = leader.id
        else:
            user.leader_id = None
    if "primary_department_id" in fields:
        target_department_id = (
            _get_active_department(db, payload.primary_department_id).id
            if payload.primary_department_id
            else None
        )
        _ensure_department_change_safe(db, user, target_department_id)
        user.primary_department_id = target_department_id

    user.revision += 1
    user.updated_at = utc_now()
    try:
        db.flush()
    except IntegrityError as error:
        raise ConflictError(
            "DISPLAY_NAME_ALREADY_EXISTS",
            "显示名称已被使用，请换一个",
        ) from error
    record_audit(
        db,
        actor=actor,
        action=(
            "user.freeze"
            if "is_active" in fields and payload.is_active is False and user.is_active is False
            else (
                "user.unfreeze"
                if "is_active" in fields and payload.is_active is True and user.is_active is True
                else "user.update"
            )
        ),
        entity_type="user",
        entity_id=user.id,
        before_data=before_data,
        after_data={
            "displayName": user.display_name,
            "role": user.role,
            "leaderId": user.leader_id,
            "primaryDepartmentId": user.primary_department_id,
            "isActive": user.is_active,
            "revision": user.revision,
        },
    )
    return UserOut.model_validate(user)


@router.patch("/{user_id}/leader", response_model=UserOut)
def update_user_leader(
    user_id: str,
    payload: UserLeaderUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> UserOut:
    permission_service.assert_permission(db, actor, PermissionKey.USERS_MANAGE)
    user = db.get(User, user_id)
    if not user or user.role == UserRole.SUPER_ADMIN.value:
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    if user.role == UserRole.SYSTEM_ADMIN.value and not is_super_admin(actor):
        raise NotFoundError("USER_NOT_FOUND", "用户不存在")
    if payload.revision != user.revision:
        raise ConflictError(
            "REVISION_CONFLICT",
            "用户资料已被其他管理员修改，请刷新后重试",
            {
                "expected_revision": payload.revision,
                "current_revision": user.revision,
            },
        )

    previous_leader_id = user.leader_id
    if payload.leader_id:
        leader = _get_assignable_leader(db, payload.leader_id)
        _ensure_no_leader_cycle(db, user, leader)
        user.leader_id = leader.id
    else:
        user.leader_id = None
    user.revision += 1
    user.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="user.leader.update",
        entity_type="user",
        entity_id=user.id,
        before_data={"leaderId": previous_leader_id},
        after_data={"leaderId": user.leader_id, "revision": user.revision},
    )
    return UserOut.model_validate(user)
