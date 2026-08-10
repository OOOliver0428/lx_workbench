from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import is_super_admin
from app.errors import AppError, ConflictError, PermissionDeniedError
from app.models import PermissionKey, User, UserPermission, UserRole, utc_now


@dataclass(frozen=True)
class PermissionDefinition:
    key: PermissionKey
    group: str
    group_label: str
    label: str
    description: str
    system_admin_assignable: bool = True
    requires_team_scope: bool = False


PERMISSION_CATALOG = (
    PermissionDefinition(
        PermissionKey.DASHBOARD_OPPORTUNITY_VIEW,
        "dashboard",
        "作战台视图",
        "商机追踪",
        "查看作战台的商机清单、阶段分布和项目关系图。",
    ),
    PermissionDefinition(
        PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS,
        "dashboard",
        "作战台视图",
        "录入商机进展",
        "查看商机追踪，并为有权限管理的商机录入阶段进展。",
    ),
    PermissionDefinition(
        PermissionKey.DASHBOARD_OPPORTUNITY_CREATE,
        "dashboard",
        "作战台视图",
        "新建商机",
        "查看商机追踪、录入进展并创建新的商机。",
    ),
    PermissionDefinition(
        PermissionKey.DASHBOARD_WORK_VIEW,
        "dashboard",
        "作战台视图",
        "工作管理",
        "查看成员提交、交付物和项目工作摘要；仅团队负责人及以上且有直属成员时生效。",
        requires_team_scope=True,
    ),
    PermissionDefinition(
        PermissionKey.DASHBOARD_OVERVIEW_VIEW,
        "dashboard",
        "作战台视图",
        "周期总览",
        "查看跨周趋势、提交矩阵和阶段推进时间线。",
    ),
    PermissionDefinition(
        PermissionKey.DASHBOARD_TEAM_SUMMARY,
        "dashboard",
        "作战台视图",
        "生成团队 AI 总结",
        "查看工作管理并使用已提交周报生成团队总结；仅有直属成员的团队负责人及以上可用。",
        requires_team_scope=True,
    ),
    PermissionDefinition(
        PermissionKey.PROJECTS_VIEW,
        "projects",
        "项目管理",
        "查看项目",
        "进入项目模块并读取项目主数据。",
    ),
    PermissionDefinition(
        PermissionKey.PROJECTS_EDIT,
        "projects",
        "项目管理",
        "编辑项目",
        "编辑、流转、合并项目并维护成员、标签和进展。",
    ),
    PermissionDefinition(
        PermissionKey.PROJECTS_CREATE,
        "projects",
        "项目管理",
        "创建项目",
        "创建项目，同时包含项目编辑和查看权限。",
    ),
    PermissionDefinition(
        PermissionKey.DEPARTMENTS_VIEW,
        "department_works",
        "部门工作",
        "查看部门目录",
        "读取有效部门目录和本人主部门信息。",
    ),
    PermissionDefinition(
        PermissionKey.DEPARTMENTS_MANAGE,
        "department_works",
        "部门工作",
        "管理部门",
        "创建、修改和停用部门并指定部门负责人。",
        system_admin_assignable=False,
    ),
    PermissionDefinition(
        PermissionKey.DEPARTMENT_WORKS_VIEW,
        "department_works",
        "部门工作",
        "查看部门工作",
        "查看公开事项和本人主部门范围内的部门工作。",
    ),
    PermissionDefinition(
        PermissionKey.DEPARTMENT_WORKS_EDIT,
        "department_works",
        "部门工作",
        "维护部门工作",
        "在本人主部门范围内维护部门工作；公开范围不扩大编辑权限。",
    ),
    PermissionDefinition(
        PermissionKey.DEPARTMENT_WORKS_CREATE,
        "department_works",
        "部门工作",
        "创建部门工作",
        "在本人主部门中创建部门工作，同时包含编辑和查看权限。",
    ),
    PermissionDefinition(
        PermissionKey.TASKS_VIEW,
        "tasks",
        "任务管理",
        "查看任务",
        "进入任务模块并读取任务与协作信息。",
    ),
    PermissionDefinition(
        PermissionKey.TASKS_EDIT,
        "tasks",
        "任务管理",
        "编辑任务",
        "编辑、流转、改派任务并建立跨项目任务关联。",
    ),
    PermissionDefinition(
        PermissionKey.TASKS_CREATE,
        "tasks",
        "任务管理",
        "创建任务",
        "创建任务，同时包含任务编辑和查看权限。",
    ),
    PermissionDefinition(
        PermissionKey.WORK_RECORDS_VIEW,
        "work_records",
        "工作记录",
        "查看工作记录",
        "进入工作记录模块；普通用户仍只能读取自己的原始记录。",
    ),
    PermissionDefinition(
        PermissionKey.WORK_RECORDS_MANAGE,
        "work_records",
        "工作记录",
        "维护工作记录",
        "创建、编辑和删除自己的工作记录；仅超级管理员可操作他人记录。",
    ),
    PermissionDefinition(
        PermissionKey.WEEKLY_REPORTS_VIEW,
        "weekly_reports",
        "周报",
        "查看周报",
        "进入周报模块并按周目读取自己的个人周报。",
    ),
    PermissionDefinition(
        PermissionKey.WEEKLY_REPORTS_MANAGE,
        "weekly_reports",
        "周报",
        "维护个人周报",
        "生成、编辑并正式提交自己的周报。",
    ),
    PermissionDefinition(
        PermissionKey.AI_USE,
        "ai",
        "AI 能力",
        "使用 AI 助手",
        "打开 AI 助手并发起个人工作辅助对话。",
    ),
    PermissionDefinition(
        PermissionKey.USERS_MANAGE,
        "settings",
        "系统设置",
        "管理用户与角色",
        "创建账号、修改资料、角色和直属负责人。",
        system_admin_assignable=False,
    ),
    PermissionDefinition(
        PermissionKey.TAGS_MANAGE,
        "settings",
        "系统设置",
        "管理项目标签",
        "创建和维护系统级项目标签。",
        system_admin_assignable=False,
    ),
    PermissionDefinition(
        PermissionKey.AI_CONFIG_MANAGE,
        "settings",
        "系统设置",
        "管理大模型接入",
        "测试、保存并查看服务端大模型配置。",
        system_admin_assignable=False,
    ),
    PermissionDefinition(
        PermissionKey.AUDIT_VIEW,
        "settings",
        "系统设置",
        "查看审计记录",
        "读取系统审计记录；他人工作记录审计仍仅超级管理员可见。",
        system_admin_assignable=False,
    ),
)

PERMISSION_BY_KEY = {definition.key.value: definition for definition in PERMISSION_CATALOG}
ALL_PERMISSION_KEYS = tuple(definition.key.value for definition in PERMISSION_CATALOG)
SYSTEM_ADMIN_ASSIGNABLE_KEYS = {
    definition.key.value
    for definition in PERMISSION_CATALOG
    if definition.system_admin_assignable
}
PERMISSION_IMPLICATIONS = {
    PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS.value: {
        PermissionKey.DASHBOARD_OPPORTUNITY_VIEW.value,
    },
    PermissionKey.DASHBOARD_OPPORTUNITY_CREATE.value: {
        PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS.value,
    },
    PermissionKey.DASHBOARD_TEAM_SUMMARY.value: {
        PermissionKey.DASHBOARD_WORK_VIEW.value,
        PermissionKey.WEEKLY_REPORTS_VIEW.value,
    },
    PermissionKey.PROJECTS_EDIT.value: {
        PermissionKey.PROJECTS_VIEW.value,
    },
    PermissionKey.PROJECTS_CREATE.value: {
        PermissionKey.PROJECTS_EDIT.value,
    },
    PermissionKey.DEPARTMENTS_MANAGE.value: {
        PermissionKey.DEPARTMENTS_VIEW.value,
    },
    PermissionKey.DEPARTMENT_WORKS_EDIT.value: {
        PermissionKey.DEPARTMENT_WORKS_VIEW.value,
        PermissionKey.DEPARTMENTS_VIEW.value,
    },
    PermissionKey.DEPARTMENT_WORKS_CREATE.value: {
        PermissionKey.DEPARTMENT_WORKS_EDIT.value,
    },
    PermissionKey.TASKS_EDIT.value: {
        PermissionKey.TASKS_VIEW.value,
    },
    PermissionKey.TASKS_CREATE.value: {
        PermissionKey.TASKS_EDIT.value,
    },
    PermissionKey.TASKS_VIEW.value: {
        PermissionKey.PROJECTS_VIEW.value,
        PermissionKey.DEPARTMENT_WORKS_VIEW.value,
        PermissionKey.DEPARTMENTS_VIEW.value,
    },
    PermissionKey.WORK_RECORDS_MANAGE.value: {
        PermissionKey.WORK_RECORDS_VIEW.value,
    },
    PermissionKey.WEEKLY_REPORTS_MANAGE.value: {
        PermissionKey.WEEKLY_REPORTS_VIEW.value,
    },
}

TEAM_SCOPE_PERMISSION_KEYS = {
    PermissionKey.DASHBOARD_WORK_VIEW.value,
    PermissionKey.DASHBOARD_TEAM_SUMMARY.value,
}

DEFAULT_NEW_USER_PERMISSION_KEYS = {
    PermissionKey.PROJECTS_VIEW.value,
    PermissionKey.DEPARTMENTS_VIEW.value,
    PermissionKey.DEPARTMENT_WORKS_VIEW.value,
    PermissionKey.TASKS_VIEW.value,
    PermissionKey.WORK_RECORDS_VIEW.value,
    PermissionKey.WORK_RECORDS_MANAGE.value,
    PermissionKey.WEEKLY_REPORTS_VIEW.value,
    PermissionKey.WEEKLY_REPORTS_MANAGE.value,
    PermissionKey.AI_USE.value,
}


def assigned_permission_keys(db: Session, user_id: str) -> set[str]:
    cache = db.info.setdefault("permission_keys_by_user", {})
    if user_id in cache:
        return set(cache[user_id])
    assigned = set(
        db.scalars(
            select(UserPermission.permission_key).where(
                UserPermission.user_id == user_id
            )
        ).all()
    )
    cache[user_id] = frozenset(assigned)
    return assigned


def has_team_scope(db: Session, user: User) -> bool:
    if user.role not in {
        UserRole.TEAM_LEADER.value,
        UserRole.SYSTEM_ADMIN.value,
        UserRole.SUPER_ADMIN.value,
    }:
        return False
    return db.scalar(
        select(User.id)
        .where(
            User.leader_id == user.id,
            User.is_active.is_(True),
        )
        .limit(1)
    ) is not None


def _eligible_assigned_permissions(
    db: Session,
    user: User,
    assigned: set[str],
) -> set[str]:
    if has_team_scope(db, user):
        return assigned
    return assigned - TEAM_SCOPE_PERMISSION_KEYS


def effective_permission_keys(db: Session, user: User) -> list[str]:
    if is_super_admin(user):
        return list(ALL_PERMISSION_KEYS)
    assigned = _eligible_assigned_permissions(
        db,
        user,
        assigned_permission_keys(db, user.id),
    )
    effective = _expand_permissions(assigned)
    return [key for key in ALL_PERMISSION_KEYS if key in effective]


def has_permission(db: Session, user: User, key: PermissionKey | str) -> bool:
    if is_super_admin(user):
        return True
    permission_key = key.value if isinstance(key, PermissionKey) else key
    assigned = _eligible_assigned_permissions(
        db,
        user,
        assigned_permission_keys(db, user.id),
    )
    return permission_key in _expand_permissions(assigned)


def _expand_permissions(assigned: set[str]) -> set[str]:
    effective = set(assigned)
    pending = list(assigned)
    while pending:
        permission = pending.pop()
        for implied in PERMISSION_IMPLICATIONS.get(permission, set()):
            if implied not in effective:
                effective.add(implied)
                pending.append(implied)
    return effective


def assert_permission(
    db: Session,
    user: User,
    key: PermissionKey | str,
    message: str = "当前账号未获得此功能权限",
) -> None:
    if not has_permission(db, user, key):
        raise PermissionDeniedError(message)


def assert_any_permission(
    db: Session,
    user: User,
    keys: tuple[PermissionKey | str, ...],
    message: str = "当前账号未获得此功能权限",
) -> None:
    if not any(has_permission(db, user, key) for key in keys):
        raise PermissionDeniedError(message)


def is_permission_manager(user: User) -> bool:
    return user.role in {
        UserRole.SYSTEM_ADMIN.value,
        UserRole.SUPER_ADMIN.value,
    }


def assert_permission_manager(user: User) -> None:
    if not is_permission_manager(user):
        raise PermissionDeniedError("只有系统管理员可以分配权限")


def _assert_assignment_target(actor: User, target: User) -> None:
    assert_permission_manager(actor)
    if target.role == UserRole.SUPER_ADMIN.value:
        raise AppError("SUPER_ADMIN_HIDDEN", "用户不存在", status_code=404)
    if is_super_admin(actor):
        return
    if target.role not in {
        UserRole.MEMBER.value,
        UserRole.TEAM_LEADER.value,
    }:
        raise PermissionDeniedError("系统管理员只能配置团队负责人和团队成员")


def replace_user_permissions(
    db: Session,
    *,
    actor: User,
    target: User,
    expected_revision: int,
    requested_keys: set[str],
) -> list[str]:
    _assert_assignment_target(actor, target)
    if expected_revision != target.revision:
        raise ConflictError(
            "USER_REVISION_CONFLICT",
            "用户权限已被其他管理员修改，请刷新后重试",
            {
                "expected_revision": expected_revision,
                "current_revision": target.revision,
            },
        )
    unknown = requested_keys - set(ALL_PERMISSION_KEYS)
    if unknown:
        raise AppError(
            "UNKNOWN_PERMISSION",
            "包含系统无法识别的权限项",
            {"permissions": sorted(unknown)},
        )

    existing = assigned_permission_keys(db, target.id)
    desired = _expand_permissions(set(requested_keys))
    if desired & TEAM_SCOPE_PERMISSION_KEYS and not has_team_scope(db, target):
        raise AppError(
            "TEAM_SCOPE_PERMISSION_INELIGIBLE",
            "工作管理权限仅可授予有直属成员的团队负责人或系统管理员",
        )
    if not is_super_admin(actor):
        protected_existing = existing - SYSTEM_ADMIN_ASSIGNABLE_KEYS
        protected_requested = desired - SYSTEM_ADMIN_ASSIGNABLE_KEYS
        if protected_requested != protected_existing:
            raise PermissionDeniedError("系统管理员不能变更系统级权限")
        desired = (desired & SYSTEM_ADMIN_ASSIGNABLE_KEYS) | protected_existing

    db.execute(
        delete(UserPermission).where(
            UserPermission.user_id == target.id,
            UserPermission.permission_key.not_in(desired),
        )
    )
    for key in desired - existing:
        db.add(
            UserPermission(
                user_id=target.id,
                permission_key=key,
                granted_by=actor.id,
            )
        )
    db.info.setdefault("permission_keys_by_user", {})[target.id] = frozenset(
        desired
    )
    target.revision += 1
    target.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="user.permissions.replace",
        entity_type="user",
        entity_id=target.id,
        before_data={"permissions": sorted(existing)},
        after_data={
            "permissions": sorted(desired),
            "revision": target.revision,
        },
    )
    db.flush()
    return [key for key in ALL_PERMISSION_KEYS if key in desired]


def grant_initial_permissions(
    db: Session,
    *,
    user: User,
    actor: User,
) -> list[str]:
    desired = _expand_permissions(set(DEFAULT_NEW_USER_PERMISSION_KEYS))
    for key in desired:
        db.add(
            UserPermission(
                user_id=user.id,
                permission_key=key,
                granted_by=actor.id,
            )
        )
    db.info.setdefault("permission_keys_by_user", {})[user.id] = frozenset(desired)
    db.flush()
    return [key for key in ALL_PERMISSION_KEYS if key in desired]
