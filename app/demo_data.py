from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain import normalize_name
from app.errors import ConflictError
from app.models import (
    AttentionStatus,
    AuditEvent,
    AuthSession,
    BusinessStage,
    Deliverable,
    Opportunity,
    OpportunityMember,
    OpportunityProgress,
    OpportunityStatus,
    PermissionKey,
    Project,
    ProjectAlias,
    ProjectMember,
    ProjectMemberRole,
    ProjectMerge,
    ProjectProgress,
    ProjectStatus,
    ProjectTag,
    ProjectTagAssignment,
    Task,
    TaskAssignmentHistory,
    TaskCollaborator,
    TaskPriority,
    TaskRelation,
    TaskStatus,
    TeamWeeklySummary,
    User,
    UserPermission,
    UserRole,
    WeeklyReport,
    WorkRecord,
)
from app.security import hash_password
from app.services import permissions as permission_service

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
DEMO_NAMESPACE = uuid.UUID("27e584ca-23c1-4d09-b07c-90cd6a3bcb40")
DEMO_LOGIN_NAMES = (
    "demo_root",
    "demo_admin",
    "demo_leader",
    "demo_full",
    "demo_opportunity",
    "demo_personal",
    "demo_newcomer",
    "demo_inactive",
)
STAGE_LABELS = {
    BusinessStage.LEAD.value: "线索",
    BusinessStage.REQUIREMENT.value: "需求确认",
    BusinessStage.SOLUTION_EXCHANGE.value: "方案交流",
    BusinessStage.SOLUTION_CONFIRM.value: "方案确认",
    BusinessStage.POC.value: "POC 验证",
    BusinessStage.TENDER.value: "商务招投标",
    BusinessStage.WON.value: "赢单签约",
}


def _demo_id(entity_type: str, key: str) -> str:
    return str(uuid.uuid5(DEMO_NAMESPACE, f"{entity_type}:{key}"))


def _week_start(today: date | None = None) -> date:
    value = today or datetime.now(SHANGHAI).date()
    return value - timedelta(days=value.weekday())


def _at(local_date: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.combine(
        local_date,
        time(hour=hour, minute=minute),
        tzinfo=SHANGHAI,
    ).astimezone(UTC)


def _upsert(
    db: Session,
    model: type[Any],
    primary_key: str,
    **values: Any,
) -> Any:
    entity = db.get(model, primary_key)
    if entity is None:
        entity = model(id=primary_key, **values)
        db.add(entity)
        return entity
    for field, value in values.items():
        setattr(entity, field, value)
    return entity


def _assert_user_identity_available(
    db: Session,
    *,
    user_id: str,
    login_name: str,
    display_name: str,
) -> None:
    display_name_key = display_name.strip().casefold()
    conflicting_user = db.scalar(
        select(User).where(
            User.id != user_id,
            (User.login_name == login_name) | (User.display_name_key == display_name_key),
        )
    )
    if conflicting_user:
        raise ConflictError(
            "DEMO_USER_IDENTITY_CONFLICT",
            f"无法创建演示账号 {login_name}：登录名或显示名称已被使用",
        )


def _seed_users(
    db: Session,
    *,
    password: str,
) -> dict[str, User]:
    definitions = {
        "root": (
            "demo_root",
            "演示·超级管理员",
            UserRole.SUPER_ADMIN.value,
            None,
            "paper-01",
            True,
        ),
        "admin": (
            "demo_admin",
            "演示·系统管理员",
            UserRole.SYSTEM_ADMIN.value,
            None,
            "line-02",
            True,
        ),
        "leader": (
            "demo_leader",
            "演示·团队负责人",
            UserRole.TEAM_LEADER.value,
            "admin",
            "clay-soft-03",
            True,
        ),
        "full": (
            "demo_full",
            "演示·方案顾问（全功能）",
            UserRole.MEMBER.value,
            "leader",
            "flat-01",
            True,
        ),
        "opportunity": (
            "demo_opportunity",
            "演示·售前顾问（商机视图）",
            UserRole.MEMBER.value,
            "leader",
            "pixel-soft-04",
            True,
        ),
        "personal": (
            "demo_personal",
            "演示·交付顾问（个人工作）",
            UserRole.MEMBER.value,
            "leader",
            "clay-05",
            True,
        ),
        "newcomer": (
            "demo_newcomer",
            "演示·新成员（初始权限）",
            UserRole.MEMBER.value,
            "leader",
            "line-06",
            True,
        ),
        "inactive": (
            "demo_inactive",
            "演示·已停用成员",
            UserRole.MEMBER.value,
            "leader",
            "pixel-08",
            False,
        ),
    }
    users: dict[str, User] = {}
    now = datetime.now(UTC)
    for key, (
        login_name,
        display_name,
        role,
        _leader_key,
        avatar_key,
        is_active,
    ) in definitions.items():
        user_id = _demo_id("user", key)
        _assert_user_identity_available(
            db,
            user_id=user_id,
            login_name=login_name,
            display_name=display_name,
        )
        users[key] = _upsert(
            db,
            User,
            user_id,
            login_name=login_name,
            display_name=display_name,
            password_hash=hash_password(password),
            role=role,
            leader_id=None,
            avatar_key=avatar_key,
            is_active=is_active,
            must_change_password=False,
            last_login_at=None,
            created_at=now,
            updated_at=now,
            revision=1,
        )
    db.flush()
    for key, definition in definitions.items():
        leader_key = definition[3]
        users[key].leader_id = users[leader_key].id if leader_key else None
    db.execute(
        delete(AuthSession).where(
            AuthSession.user_id.in_(user.id for user in users.values())
        )
    )
    return users


def _seed_permissions(db: Session, users: dict[str, User]) -> int:
    all_permissions = {permission.value for permission in PermissionKey}
    business_full = {
        PermissionKey.DASHBOARD_OPPORTUNITY_VIEW.value,
        PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS.value,
        PermissionKey.DASHBOARD_OPPORTUNITY_CREATE.value,
        PermissionKey.DASHBOARD_WORK_VIEW.value,
        PermissionKey.DASHBOARD_OVERVIEW_VIEW.value,
        PermissionKey.DASHBOARD_TEAM_SUMMARY.value,
        PermissionKey.PROJECTS_VIEW.value,
        PermissionKey.PROJECTS_EDIT.value,
        PermissionKey.PROJECTS_CREATE.value,
        PermissionKey.TASKS_VIEW.value,
        PermissionKey.TASKS_EDIT.value,
        PermissionKey.TASKS_CREATE.value,
        PermissionKey.WORK_RECORDS_VIEW.value,
        PermissionKey.WORK_RECORDS_MANAGE.value,
        PermissionKey.WEEKLY_REPORTS_VIEW.value,
        PermissionKey.WEEKLY_REPORTS_MANAGE.value,
        PermissionKey.AI_USE.value,
    }
    permission_sets = {
        "admin": all_permissions,
        "leader": business_full,
        "full": business_full
        - {
            PermissionKey.DASHBOARD_WORK_VIEW.value,
            PermissionKey.DASHBOARD_TEAM_SUMMARY.value,
        },
        "opportunity": {
            PermissionKey.DASHBOARD_OPPORTUNITY_VIEW.value,
            PermissionKey.PROJECTS_VIEW.value,
            PermissionKey.TASKS_VIEW.value,
        },
        "personal": {
            PermissionKey.PROJECTS_VIEW.value,
            PermissionKey.TASKS_VIEW.value,
            PermissionKey.WORK_RECORDS_VIEW.value,
            PermissionKey.WORK_RECORDS_MANAGE.value,
            PermissionKey.WEEKLY_REPORTS_VIEW.value,
            PermissionKey.WEEKLY_REPORTS_MANAGE.value,
            PermissionKey.AI_USE.value,
        },
        "newcomer": set(permission_service.DEFAULT_NEW_USER_PERMISSION_KEYS),
        "inactive": business_full,
    }
    target_ids = [users[key].id for key in permission_sets]
    db.execute(delete(UserPermission).where(UserPermission.user_id.in_(target_ids)))
    db.flush()
    count = 0
    for user_key, permissions in permission_sets.items():
        for permission_key in sorted(permissions):
            db.add(
                UserPermission(
                    id=_demo_id("permission", f"{user_key}:{permission_key}"),
                    user_id=users[user_key].id,
                    permission_key=permission_key,
                    granted_by=users["root"].id,
                )
            )
            count += 1
    return count


def _seed_tags(db: Session, users: dict[str, User]) -> dict[str, ProjectTag]:
    tags: dict[str, ProjectTag] = {}
    for key, name in (("opportunity", "商机"), ("change", "改造")):
        tag = db.scalar(
            select(ProjectTag).where(ProjectTag.normalized_name == normalize_name(name))
        )
        if not tag:
            tag = _upsert(
                db,
                ProjectTag,
                _demo_id("tag", key),
                name=name,
                normalized_name=normalize_name(name),
                description=f"{name}类项目",
                color="#3468C0",
                sort_order=10 if key == "opportunity" else 20,
                is_active=True,
                deleted_at=None,
                deleted_by=None,
            )
        tags[key] = tag
    for key, name, description, color, sort_order in (
        ("focus", "重点客户", "需要持续关注的战略客户", "#C2413A", 30),
        ("poc", "POC", "处于概念验证或试点阶段", "#7C3AED", 40),
        ("internal", "内部建设", "部门内部能力建设项目", "#0F766E", 50),
    ):
        tag_id = _demo_id("tag", key)
        existing = db.scalar(
            select(ProjectTag).where(
                ProjectTag.normalized_name == normalize_name(name),
                ProjectTag.id != tag_id,
            )
        )
        if existing:
            tags[key] = existing
            continue
        tags[key] = _upsert(
            db,
            ProjectTag,
            tag_id,
            name=name,
            normalized_name=normalize_name(name),
            description=description,
            color=color,
            sort_order=sort_order,
            is_active=True,
            deleted_at=None,
            deleted_by=None,
        )
    db.flush()
    return tags


def _seed_projects(
    db: Session,
    users: dict[str, User],
    tags: dict[str, ProjectTag],
    *,
    current_week: date,
) -> dict[str, Project]:
    project_definitions = {
        "energy": {
            "code": "DEMO-OPP-001",
            "name": "【演示】华东能源数字化平台",
            "description": "集团级数字化平台商机，覆盖统一门户、数据治理和移动协作。",
            "status": ProjectStatus.ACTIVE.value,
            "owner": "full",
            "parent": None,
            "start": current_week - timedelta(weeks=8),
            "end": current_week + timedelta(weeks=5),
            "tags": ("opportunity", "focus"),
        },
        "bank_ai": {
            "code": "DEMO-OPP-002",
            "name": "【演示】城商行知识助手",
            "description": "面向客服与客户经理的企业知识助手 POC。",
            "status": ProjectStatus.ACTIVE.value,
            "owner": "leader",
            "parent": None,
            "start": current_week - timedelta(weeks=5),
            "end": current_week + timedelta(weeks=3),
            "tags": ("opportunity", "poc", "focus"),
        },
        "park": {
            "code": "DEMO-OPP-003",
            "name": "【演示】智慧园区数据中台",
            "description": "园区管委会数据中台前期需求澄清。",
            "status": ProjectStatus.PENDING.value,
            "owner": "opportunity",
            "parent": None,
            "start": current_week,
            "end": current_week + timedelta(weeks=10),
            "tags": ("opportunity",),
        },
        "mobile": {
            "code": "DEMO-CHG-001",
            "name": "【演示】制造集团移动门户改造",
            "description": "存量移动门户信创与安全适配，当前等待终端基线确认。",
            "status": ProjectStatus.PAUSED.value,
            "owner": "personal",
            "parent": None,
            "start": current_week - timedelta(weeks=7),
            "end": current_week + timedelta(weeks=2),
            "tags": ("change", "focus"),
        },
        "retail": {
            "code": "DEMO-PRJ-001",
            "name": "【演示】零售会员运营平台",
            "description": "已完成上线验收，用于展示赢单与已完成状态。",
            "status": ProjectStatus.COMPLETED.value,
            "owner": "personal",
            "parent": None,
            "start": current_week - timedelta(weeks=16),
            "end": current_week - timedelta(weeks=1),
            "tags": ("change",),
        },
        "framework": {
            "code": "DEMO-PRJ-002",
            "name": "【演示】央企数字化转型框架",
            "description": "集团级咨询框架主项目。",
            "status": ProjectStatus.ACTIVE.value,
            "owner": "leader",
            "parent": None,
            "start": current_week - timedelta(weeks=10),
            "end": current_week + timedelta(weeks=12),
            "tags": ("opportunity", "focus"),
        },
        "governance": {
            "code": "DEMO-PRJ-003",
            "name": "【演示】一期数据治理咨询",
            "description": "数字化转型框架下的数据治理子项目。",
            "status": ProjectStatus.ACTIVE.value,
            "owner": "full",
            "parent": "framework",
            "start": current_week - timedelta(weeks=3),
            "end": current_week + timedelta(weeks=6),
            "tags": ("internal",),
        },
        "legacy_ai": {
            "code": "DEMO-MRG-001",
            "name": "【演示】城商行智能问答（旧）",
            "description": "已确认与城商行知识助手为同一项目。",
            "status": ProjectStatus.MERGED.value,
            "owner": "leader",
            "parent": None,
            "start": current_week - timedelta(weeks=8),
            "end": current_week - timedelta(weeks=5),
            "tags": ("opportunity",),
        },
        "rejected": {
            "code": "DEMO-REJ-001",
            "name": "【演示】海外营销平台线索",
            "description": "预算未落实，暂不立项。",
            "status": ProjectStatus.REJECTED.value,
            "owner": "opportunity",
            "parent": None,
            "start": current_week - timedelta(weeks=2),
            "end": current_week + timedelta(weeks=8),
            "tags": ("opportunity",),
        },
        "archived": {
            "code": "DEMO-ARC-001",
            "name": "【演示】内部售前资料库一期",
            "description": "历史内部建设项目，已归档。",
            "status": ProjectStatus.ARCHIVED.value,
            "owner": "leader",
            "parent": None,
            "start": current_week - timedelta(weeks=20),
            "end": current_week - timedelta(weeks=12),
            "tags": ("internal",),
        },
    }
    projects: dict[str, Project] = {}
    approved_at = _at(current_week - timedelta(weeks=7), 14)
    for key, definition in project_definitions.items():
        project_id = _demo_id("project", key)
        conflicting_project = db.scalar(
            select(Project).where(
                Project.id != project_id,
                (
                    (Project.code == definition["code"])
                    | (
                        (Project.normalized_name == normalize_name(definition["name"]))
                        & (Project.deleted_at.is_(None))
                        & (Project.status != ProjectStatus.MERGED.value)
                    )
                ),
            )
        )
        if conflicting_project:
            raise ConflictError(
                "DEMO_PROJECT_CONFLICT",
                f"无法创建演示项目 {definition['name']}：编码或名称已被使用",
            )
        owner = users[str(definition["owner"])]
        projects[key] = _upsert(
            db,
            Project,
            project_id,
            code=definition["code"],
            name=definition["name"],
            normalized_name=normalize_name(str(definition["name"])),
            description=definition["description"],
            status=definition["status"],
            parent_project_id=None,
            owner_id=owner.id,
            proposed_by=owner.id,
            approved_by=users["leader"].id,
            approved_at=approved_at,
            rejected_reason=(
                "客户本年度预算未落实，保留线索等待下一周期。"
                if definition["status"] == ProjectStatus.REJECTED.value
                else None
            ),
            merged_into_project_id=None,
            planned_start_date=definition["start"],
            planned_end_date=definition["end"],
            deleted_at=None,
            deleted_by=None,
            created_at=_at(definition["start"], 9),
            updated_at=_at(current_week, 9),
            revision=1,
        )
    db.flush()
    for key, definition in project_definitions.items():
        parent_key = definition["parent"]
        projects[key].parent_project_id = projects[parent_key].id if parent_key else None
    projects["legacy_ai"].merged_into_project_id = projects["bank_ai"].id
    db.flush()

    member_keys = ("leader", "full", "opportunity", "personal")
    for project_key, project in projects.items():
        if project.status in {
            ProjectStatus.REJECTED.value,
            ProjectStatus.ARCHIVED.value,
            ProjectStatus.MERGED.value,
        }:
            participant_keys = (str(project_definitions[project_key]["owner"]),)
        else:
            participant_keys = member_keys
        for user_key in participant_keys:
            user = users[user_key]
            existing = db.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == user.id,
                )
            )
            membership_id = (
                existing.id
                if existing
                else _demo_id("project-member", f"{project_key}:{user_key}")
            )
            _upsert(
                db,
                ProjectMember,
                membership_id,
                project_id=project.id,
                user_id=user.id,
                role=(
                    ProjectMemberRole.OWNER.value
                    if project.owner_id == user.id
                    else ProjectMemberRole.MEMBER.value
                ),
                joined_at=_at(current_week - timedelta(weeks=4), 9),
                left_at=None,
                added_by=users["leader"].id,
            )
        for tag_key in project_definitions[project_key]["tags"]:
            tag = tags[str(tag_key)]
            existing_assignment = db.scalar(
                select(ProjectTagAssignment).where(
                    ProjectTagAssignment.project_id == project.id,
                    ProjectTagAssignment.tag_id == tag.id,
                )
            )
            assignment_id = (
                existing_assignment.id
                if existing_assignment
                else _demo_id("project-tag", f"{project_key}:{tag_key}")
            )
            _upsert(
                db,
                ProjectTagAssignment,
                assignment_id,
                project_id=project.id,
                tag_id=tag.id,
                added_by=users["leader"].id,
                added_at=_at(current_week - timedelta(weeks=4), 9),
            )

    alias = db.scalar(
        select(ProjectAlias).where(
            ProjectAlias.normalized_value
            == normalize_name(projects["legacy_ai"].name)
        )
    )
    alias_id = alias.id if alias else _demo_id("project-alias", "legacy-ai")
    _upsert(
        db,
        ProjectAlias,
        alias_id,
        project_id=projects["bank_ai"].id,
        value=projects["legacy_ai"].name,
        normalized_value=normalize_name(projects["legacy_ai"].name),
        source="merge",
        created_by=users["leader"].id,
        created_at=_at(current_week - timedelta(weeks=4), 16),
    )
    _upsert(
        db,
        ProjectMerge,
        _demo_id("project-merge", "legacy-ai"),
        source_project_id=projects["legacy_ai"].id,
        target_project_id=projects["bank_ai"].id,
        reason="演示数据：客户确认两个名称属于同一知识助手项目。",
        moved_counts={"tasks": 1, "workRecords": 2, "deliverables": 1},
        source_snapshot={"code": "DEMO-MRG-001", "status": "active"},
        target_snapshot={"code": "DEMO-OPP-002", "status": "active"},
        merged_by=users["leader"].id,
        merged_at=_at(current_week - timedelta(weeks=4), 16),
    )
    return projects


def _seed_tasks(
    db: Session,
    users: dict[str, User],
    projects: dict[str, Project],
    *,
    current_week: date,
) -> dict[str, Task]:
    definitions = {
        "energy_arch": (
            "energy",
            "完成集团统一门户总体架构",
            "full",
            TaskPriority.P0.value,
            TaskStatus.DONE.value,
            -2,
        ),
        "energy_demo": (
            "energy",
            "准备高层汇报与产品演示",
            "opportunity",
            TaskPriority.P0.value,
            TaskStatus.IN_PROGRESS.value,
            2,
        ),
        "energy_security": (
            "energy",
            "确认等保与数据出域边界",
            "personal",
            TaskPriority.P0.value,
            TaskStatus.BLOCKED.value,
            1,
        ),
        "bank_knowledge": (
            "bank_ai",
            "完成知识库切片与召回验证",
            "leader",
            TaskPriority.P1.value,
            TaskStatus.DONE.value,
            -1,
        ),
        "bank_eval": (
            "bank_ai",
            "执行客户问题集效果评测",
            "full",
            TaskPriority.P0.value,
            TaskStatus.IN_PROGRESS.value,
            3,
        ),
        "bank_data": (
            "bank_ai",
            "确认脱敏语料交付清单",
            "opportunity",
            TaskPriority.P1.value,
            TaskStatus.TODO.value,
            5,
        ),
        "park_research": (
            "park",
            "完成园区业务部门访谈",
            "opportunity",
            TaskPriority.P1.value,
            TaskStatus.IN_PROGRESS.value,
            4,
        ),
        "park_proposal": (
            "park",
            "输出数据中台初步建设建议",
            "full",
            TaskPriority.P2.value,
            TaskStatus.TODO.value,
            8,
        ),
        "mobile_compat": (
            "mobile",
            "验证国产终端推送能力",
            "personal",
            TaskPriority.P0.value,
            TaskStatus.BLOCKED.value,
            2,
        ),
        "mobile_plan": (
            "mobile",
            "完成移动门户改造方案",
            "full",
            TaskPriority.P1.value,
            TaskStatus.DONE.value,
            -3,
        ),
        "retail_acceptance": (
            "retail",
            "完成生产验收与知识转移",
            "personal",
            TaskPriority.P1.value,
            TaskStatus.DONE.value,
            -8,
        ),
        "retail_training": (
            "retail",
            "追加开展第二轮运营培训",
            "leader",
            TaskPriority.P2.value,
            TaskStatus.CANCELLED.value,
            -5,
        ),
        "framework_blueprint": (
            "framework",
            "组织集团级数字化蓝图评审",
            "leader",
            TaskPriority.P0.value,
            TaskStatus.IN_PROGRESS.value,
            6,
        ),
        "governance_standard": (
            "governance",
            "盘点核心数据标准与责任部门",
            "full",
            TaskPriority.P1.value,
            TaskStatus.TODO.value,
            7,
        ),
    }
    tasks: dict[str, Task] = {}
    for key, (
        project_key,
        title,
        owner_key,
        priority,
        status,
        due_offset,
    ) in definitions.items():
        task_id = _demo_id("task", key)
        started_at = (
            _at(current_week, 9)
            if status
            in {
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.DONE.value,
            }
            else None
        )
        completed_at = (
            _at(current_week + timedelta(days=max(due_offset, 0)), 17)
            if status == TaskStatus.DONE.value
            else None
        )
        tasks[key] = _upsert(
            db,
            Task,
            task_id,
            project_id=projects[project_key].id,
            title=title,
            description=f"全量功能测试任务：{title}",
            owner_id=users[owner_key].id,
            created_by=users["leader"].id,
            priority=priority,
            status=status,
            due_date=current_week + timedelta(days=due_offset),
            blocker_reason=(
                "等待客户安全部门确认测试环境和访问白名单。"
                if status == TaskStatus.BLOCKED.value
                else None
            ),
            result=(
                f"{title}已完成并通过内部评审。"
                if status == TaskStatus.DONE.value
                else None
            ),
            cancel_reason=(
                "客户确认首轮培训已满足上线需要。"
                if status == TaskStatus.CANCELLED.value
                else None
            ),
            started_at=started_at,
            completed_at=completed_at,
            deleted_at=None,
            deleted_by=None,
            created_at=_at(current_week - timedelta(weeks=2), 9),
            updated_at=_at(current_week, 16),
            revision=1,
        )
    db.flush()
    collaborator_map = {
        "energy_demo": ("full", "leader"),
        "energy_security": ("full",),
        "bank_eval": ("leader", "opportunity"),
        "park_research": ("full",),
        "mobile_compat": ("full", "leader"),
        "framework_blueprint": ("full", "opportunity", "personal"),
    }
    for task_key, collaborator_keys in collaborator_map.items():
        for user_key in collaborator_keys:
            user = users[user_key]
            if user.id == tasks[task_key].owner_id:
                continue
            existing = db.scalar(
                select(TaskCollaborator).where(
                    TaskCollaborator.task_id == tasks[task_key].id,
                    TaskCollaborator.user_id == user.id,
                )
            )
            collaborator_id = (
                existing.id
                if existing
                else _demo_id("task-collaborator", f"{task_key}:{user_key}")
            )
            _upsert(
                db,
                TaskCollaborator,
                collaborator_id,
                task_id=tasks[task_key].id,
                user_id=user.id,
                added_by=users["leader"].id,
                added_at=_at(current_week - timedelta(days=5), 10),
            )
    for task_key, task in tasks.items():
        _upsert(
            db,
            TaskAssignmentHistory,
            _demo_id("task-assignment", task_key),
            task_id=task.id,
            previous_owner_id=None,
            new_owner_id=task.owner_id,
            reason="演示数据初始指派",
            changed_by=users["leader"].id,
            changed_at=_at(current_week - timedelta(weeks=2), 9),
        )
    relation_definitions = (
        ("energy_demo", "bank_knowledge", "复用统一身份认证能力"),
        ("bank_data", "park_research", "共享行业知识语料规范"),
        ("mobile_compat", "energy_arch", "依赖终端安全基线"),
        ("framework_blueprint", "governance_standard", "蓝图结论驱动数据标准"),
    )
    for source_key, target_key, label in relation_definitions:
        source_id, target_id = sorted((tasks[source_key].id, tasks[target_key].id))
        existing = db.scalar(
            select(TaskRelation).where(
                TaskRelation.source_task_id == source_id,
                TaskRelation.target_task_id == target_id,
            )
        )
        relation_id = (
            existing.id
            if existing
            else _demo_id("task-relation", f"{source_key}:{target_key}")
        )
        _upsert(
            db,
            TaskRelation,
            relation_id,
            source_task_id=source_id,
            target_task_id=target_id,
            label=label,
            created_by=users["leader"].id,
            deleted_at=None,
            deleted_by=None,
            created_at=_at(current_week, 11),
            updated_at=_at(current_week, 11),
            revision=1,
        )
    return tasks


def _seed_progress(
    db: Session,
    users: dict[str, User],
    projects: dict[str, Project],
    *,
    current_week: date,
) -> int:
    sequences = {
        "energy": (
            (BusinessStage.SOLUTION_EXCHANGE.value, 38),
            (BusinessStage.SOLUTION_CONFIRM.value, 52),
            (BusinessStage.POC.value, 66),
            (BusinessStage.TENDER.value, 78),
            (BusinessStage.TENDER.value, 84),
        ),
        "bank_ai": (
            (BusinessStage.REQUIREMENT.value, 24),
            (BusinessStage.SOLUTION_EXCHANGE.value, 40),
            (BusinessStage.SOLUTION_CONFIRM.value, 55),
            (BusinessStage.POC.value, 64),
            (BusinessStage.POC.value, 70),
        ),
        "park": (
            (BusinessStage.LEAD.value, 8),
            (BusinessStage.LEAD.value, 10),
            (BusinessStage.REQUIREMENT.value, 18),
            (BusinessStage.REQUIREMENT.value, 22),
            (BusinessStage.REQUIREMENT.value, 26),
        ),
        "mobile": (
            (BusinessStage.REQUIREMENT.value, 25),
            (BusinessStage.SOLUTION_EXCHANGE.value, 38),
            (BusinessStage.SOLUTION_CONFIRM.value, 50),
            (BusinessStage.SOLUTION_CONFIRM.value, 54),
            (BusinessStage.SOLUTION_CONFIRM.value, 56),
        ),
        "retail": (
            (BusinessStage.POC.value, 70),
            (BusinessStage.TENDER.value, 84),
            (BusinessStage.WON.value, 100),
            (BusinessStage.WON.value, 100),
            (BusinessStage.WON.value, 100),
        ),
        "framework": (
            (BusinessStage.LEAD.value, 12),
            (BusinessStage.REQUIREMENT.value, 22),
            (BusinessStage.SOLUTION_EXCHANGE.value, 38),
            (BusinessStage.SOLUTION_EXCHANGE.value, 44),
            (BusinessStage.SOLUTION_CONFIRM.value, 52),
        ),
        "governance": (
            (BusinessStage.LEAD.value, 8),
            (BusinessStage.LEAD.value, 12),
            (BusinessStage.REQUIREMENT.value, 20),
            (BusinessStage.REQUIREMENT.value, 24),
            (BusinessStage.SOLUTION_EXCHANGE.value, 38),
        ),
    }
    attention_by_project = {
        "energy": AttentionStatus.FOCUS.value,
        "bank_ai": AttentionStatus.COORDINATE.value,
        "park": AttentionStatus.STEADY.value,
        "mobile": AttentionStatus.COORDINATE.value,
        "retail": AttentionStatus.STEADY.value,
        "framework": AttentionStatus.FOCUS.value,
        "governance": AttentionStatus.STEADY.value,
    }
    count = 0
    for project_key, stages in sequences.items():
        for index, (stage, percent) in enumerate(stages):
            week = current_week - timedelta(weeks=4 - index)
            _upsert(
                db,
                ProjectProgress,
                _demo_id("project-progress", f"{project_key}:{week.isoformat()}"),
                project_id=projects[project_key].id,
                week_start=week,
                business_stage=stage,
                attention_status=attention_by_project[project_key],
                progress_percent=percent,
                summary=(
                    f"{projects[project_key].name}本周推进至"
                    f"{STAGE_LABELS[stage]}阶段，关键事项按计划推进。"
                ),
                output_summary=(
                    f"{projects[project_key].name.replace('【演示】', '')}阶段成果包"
                    if index in {2, 4}
                    else None
                ),
                created_by=users["leader"].id,
                created_at=_at(week + timedelta(days=4), 16),
                updated_at=_at(week + timedelta(days=4), 16),
                revision=1,
            )
            count += 1
    return count


def _seed_opportunities(
    db: Session,
    users: dict[str, User],
    projects: dict[str, Project],
    *,
    current_week: date,
) -> tuple[int, int]:
    db.flush()
    tracked_project_keys = (
        "energy",
        "bank_ai",
        "park",
        "mobile",
        "retail",
        "framework",
        "governance",
    )
    opportunity_count = 0
    progress_count = 0
    for project_key in tracked_project_keys:
        project = projects[project_key]
        existing = db.scalar(
            select(Opportunity).where(
                Opportunity.linked_project_id == project.id,
                Opportunity.deleted_at.is_(None),
            )
        )
        opportunity_id = (
            existing.id if existing else _demo_id("opportunity", project_key)
        )
        project_progress = list(
            db.scalars(
                select(ProjectProgress)
                .where(ProjectProgress.project_id == project.id)
                .order_by(ProjectProgress.week_start, ProjectProgress.created_at)
            ).all()
        )
        latest = project_progress[-1]
        opportunity = _upsert(
            db,
            Opportunity,
            opportunity_id,
            code=f"DEMO-OPP-{project_key.upper()}",
            name=project.name,
            normalized_name=normalize_name(project.name),
            customer_name=project.name.replace("【演示】", "").split("·")[0],
            description=f"由演示项目 {project.code} 迁移并保持商业推进独立记录。",
            owner_id=project.owner_id,
            created_by=users["leader"].id,
            status=(
                OpportunityStatus.WON.value
                if latest.business_stage == BusinessStage.WON.value
                else OpportunityStatus.ACTIVE.value
            ),
            business_stage=latest.business_stage,
            attention_status=latest.attention_status,
            progress_percent=latest.progress_percent,
            linked_project_id=project.id,
            project_linked_at=_at(current_week - timedelta(weeks=4), 10),
            deleted_at=None,
            deleted_by=None,
            created_at=_at(current_week - timedelta(weeks=4), 10),
            updated_at=latest.updated_at,
            revision=1,
        )
        db.flush()
        member_ids = set(
            db.scalars(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.left_at.is_(None),
                )
            ).all()
        ) | {project.owner_id}
        for user_id in member_ids:
            membership = db.scalar(
                select(OpportunityMember).where(
                    OpportunityMember.opportunity_id == opportunity.id,
                    OpportunityMember.user_id == user_id,
                )
            )
            _upsert(
                db,
                OpportunityMember,
                (
                    membership.id
                    if membership
                    else _demo_id(
                        "opportunity-member",
                        f"{project_key}:{user_id}",
                    )
                ),
                opportunity_id=opportunity.id,
                user_id=user_id,
                added_by=users["leader"].id,
                added_at=_at(current_week - timedelta(weeks=4), 10),
            )
        for project_event in project_progress:
            existing_event = db.scalar(
                select(OpportunityProgress)
                .where(
                    OpportunityProgress.opportunity_id == opportunity.id,
                    OpportunityProgress.week_start == project_event.week_start,
                )
                .order_by(OpportunityProgress.created_at)
                .limit(1)
            )
            _upsert(
                db,
                OpportunityProgress,
                (
                    existing_event.id
                    if existing_event
                    else _demo_id(
                        "opportunity-progress",
                        f"{project_key}:{project_event.week_start.isoformat()}",
                    )
                ),
                opportunity_id=opportunity.id,
                week_start=project_event.week_start,
                business_stage=project_event.business_stage,
                attention_status=project_event.attention_status,
                progress_percent=project_event.progress_percent,
                summary=project_event.summary,
                output_summary=project_event.output_summary,
                created_by=project_event.created_by,
                created_at=project_event.created_at,
                updated_at=project_event.updated_at,
                revision=1,
            )
            progress_count += 1
        opportunity_count += 1

    standalone = _upsert(
        db,
        Opportunity,
        _demo_id("opportunity", "standalone-cloud"),
        code="DEMO-OPP-STANDALONE",
        name="【演示】政务云安全运营平台",
        normalized_name=normalize_name("【演示】政务云安全运营平台"),
        customer_name="市政务云管理中心",
        description="已完成需求澄清，准备从商机创建项目主数据。",
        owner_id=users["full"].id,
        created_by=users["leader"].id,
        status=OpportunityStatus.ACTIVE.value,
        business_stage=BusinessStage.SOLUTION_EXCHANGE.value,
        attention_status=AttentionStatus.FOCUS.value,
        progress_percent=42,
        linked_project_id=None,
        project_linked_at=None,
        deleted_at=None,
        deleted_by=None,
        created_at=_at(current_week - timedelta(weeks=2), 10),
        updated_at=_at(current_week + timedelta(days=4), 15),
        revision=1,
    )
    db.flush()
    _upsert(
        db,
        OpportunityMember,
        _demo_id("opportunity-member", "standalone-cloud:full"),
        opportunity_id=standalone.id,
        user_id=users["full"].id,
        added_by=users["leader"].id,
        added_at=_at(current_week - timedelta(weeks=2), 10),
    )
    _upsert(
        db,
        OpportunityProgress,
        _demo_id("opportunity-progress", "standalone-cloud:current"),
        opportunity_id=standalone.id,
        week_start=current_week,
        business_stage=BusinessStage.SOLUTION_EXCHANGE.value,
        attention_status=AttentionStatus.FOCUS.value,
        progress_percent=42,
        summary="完成安全运营范围确认并进入方案交流。",
        output_summary="安全运营蓝图初稿",
        created_by=users["full"].id,
        created_at=_at(current_week + timedelta(days=4), 15),
        updated_at=_at(current_week + timedelta(days=4), 15),
        revision=1,
    )
    return opportunity_count + 1, progress_count + 1


def _seed_work_records(
    db: Session,
    users: dict[str, User],
    projects: dict[str, Project],
    tasks: dict[str, Task],
    *,
    current_week: date,
) -> tuple[dict[str, WorkRecord], int]:
    current_records = {
        "full_arch": (
            "full",
            0,
            "完成集团统一门户总体架构评审并关闭三项意见。",
            240,
            "energy",
            "energy_arch",
            None,
            "准备面向客户高层的价值汇报材料。",
        ),
        "full_eval": (
            "full",
            1,
            "完成知识助手客户问题集首轮效果评测。",
            180,
            "bank_ai",
            "bank_eval",
            "长文本问题召回率仍低于目标。",
            "补充语料并调整分段策略。",
        ),
        "full_standard": (
            "full",
            2,
            "梳理一期数据治理涉及的核心数据标准。",
            150,
            "governance",
            "governance_standard",
            None,
            "约访三个核心业务部门。",
        ),
        "full_unassigned": (
            "full",
            3,
            "参加部门售前方法论复盘，整理可复用检查清单。",
            90,
            None,
            None,
            None,
            "将检查清单补充进内部知识库。",
        ),
        "opportunity_demo": (
            "opportunity",
            1,
            "完成华东能源高层汇报脚本和演示路径彩排。",
            210,
            "energy",
            "energy_demo",
            "客户参会范围尚未最终确认。",
            "与客户经理确认参会领导和关注重点。",
        ),
        "opportunity_research": (
            "opportunity",
            2,
            "完成智慧园区三个业务部门访谈。",
            180,
            "park",
            "park_research",
            None,
            "汇总业务痛点并输出需求优先级。",
        ),
        "personal_mobile": (
            "personal",
            0,
            "完成两款国产终端的推送能力验证。",
            240,
            "mobile",
            "mobile_compat",
            "客户测试环境白名单尚未开通。",
            "推动安全部门开通测试环境。",
        ),
        "personal_acceptance": (
            "personal",
            3,
            "完成零售会员运营平台上线后回访。",
            150,
            "retail",
            "retail_acceptance",
            None,
            "整理上线复盘并归档。",
        ),
        "leader_bank": (
            "leader",
            1,
            "组织知识助手 POC 周例会并确认评测口径。",
            150,
            "bank_ai",
            "bank_knowledge",
            "客户脱敏语料交付较原计划延迟。",
            "协调客户数据团队明确交付日期。",
        ),
        "leader_blueprint": (
            "leader",
            4,
            "组织集团级数字化蓝图内部预审。",
            150,
            "framework",
            "framework_blueprint",
            None,
            "根据评审意见调整建设路线图。",
        ),
        "newcomer_learning": (
            "newcomer",
            2,
            "完成产品资料和项目管理规范入职学习。",
            120,
            None,
            None,
            None,
            "跟随导师参加下一次客户需求访谈。",
        ),
    }
    records: dict[str, WorkRecord] = {}
    for key, (
        user_key,
        day_offset,
        content,
        minutes,
        project_key,
        task_key,
        risk,
        next_action,
    ) in current_records.items():
        work_date = current_week + timedelta(days=day_offset)
        records[key] = _upsert(
            db,
            WorkRecord,
            _demo_id("work-record", key),
            author_id=users[user_key].id,
            work_date=work_date,
            content=content,
            minutes=minutes,
            project_id=projects[project_key].id if project_key else None,
            task_id=tasks[task_key].id if task_key else None,
            risk=risk,
            next_action=next_action,
            last_edited_by=users[user_key].id,
            delegated_edit_reason=None,
            deleted_at=None,
            deleted_by=None,
            created_at=_at(work_date, 18),
            updated_at=_at(work_date, 18),
            revision=1,
        )

    historical_project_keys = ("energy", "bank_ai", "park", "mobile", "framework")
    active_business_users = ("leader", "full", "opportunity", "personal", "newcomer")
    for week_index in range(1, 5):
        week = current_week - timedelta(weeks=week_index)
        for user_index, user_key in enumerate(active_business_users):
            project_key = historical_project_keys[(week_index + user_index) % len(
                historical_project_keys
            )]
            key = f"history-{week_index}-{user_key}"
            work_date = week + timedelta(days=(user_index + week_index) % 5)
            records[key] = _upsert(
                db,
                WorkRecord,
                _demo_id("work-record", key),
                author_id=users[user_key].id,
                work_date=work_date,
                content=(
                    f"第{week_index}周演示记录：推进"
                    f"{projects[project_key].name.replace('【演示】', '')}相关事项。"
                ),
                minutes=120 + ((user_index + week_index) % 4) * 30,
                project_id=projects[project_key].id,
                task_id=None,
                risk=(
                    "跨部门反馈时间存在不确定性。"
                    if (user_index + week_index) % 4 == 0
                    else None
                ),
                next_action="按周计划继续推进并同步关键结论。",
                last_edited_by=users[user_key].id,
                delegated_edit_reason=None,
                deleted_at=None,
                deleted_by=None,
                created_at=_at(work_date, 18),
                updated_at=_at(work_date, 18),
                revision=1,
            )
    db.flush()
    deliverable_specs = (
        (
            "energy-architecture",
            "energy",
            "full_arch",
            None,
            "统一门户总体架构 V1.0",
            "https://demo.example/deliverables/energy-architecture",
        ),
        (
            "bank-evaluation",
            "bank_ai",
            "full_eval",
            None,
            "知识助手 POC 评测报告",
            "https://demo.example/deliverables/bank-evaluation",
        ),
        (
            "park-interviews",
            "park",
            "opportunity_research",
            None,
            "智慧园区访谈纪要",
            "https://demo.example/deliverables/park-interviews",
        ),
        (
            "mobile-matrix",
            "mobile",
            "personal_mobile",
            None,
            "国产终端兼容性矩阵",
            "https://demo.example/deliverables/mobile-matrix",
        ),
        (
            "blueprint-roadmap",
            "framework",
            None,
            "framework_blueprint",
            "集团数字化建设路线图",
            "https://demo.example/deliverables/blueprint-roadmap",
        ),
        (
            "governance-catalog",
            "governance",
            None,
            "governance_standard",
            "核心数据标准目录草案",
            "https://demo.example/deliverables/governance-catalog",
        ),
        (
            "bank-weekly-meeting",
            "bank_ai",
            "leader_bank",
            None,
            "知识助手 POC 周会纪要",
            "https://demo.example/deliverables/bank-weekly-meeting",
        ),
        (
            "blueprint-review",
            "framework",
            "leader_blueprint",
            None,
            "集团数字化蓝图预审纪要",
            "https://demo.example/deliverables/blueprint-review",
        ),
    )
    for key, project_key, record_key, task_key, name, url in deliverable_specs:
        _upsert(
            db,
            Deliverable,
            _demo_id("deliverable", key),
            project_id=projects[project_key].id,
            work_record_id=records[record_key].id if record_key else None,
            task_id=tasks[task_key].id if task_key else None,
            name=name,
            url=url,
            created_by=(
                records[record_key].author_id
                if record_key
                else tasks[task_key].owner_id
            ),
            deleted_at=None,
            deleted_by=None,
            created_at=_at(current_week + timedelta(days=3), 17),
            updated_at=_at(current_week + timedelta(days=3), 17),
            revision=1,
        )
    return records, len(deliverable_specs)


def _report_content(
    user: User,
    week: date,
    *,
    current: bool,
) -> str:
    period = "本周" if current else f"{week:%m/%d} 当周"
    return (
        f"# {period}周报\n\n"
        f"## 项目进展\n"
        f"- {user.display_name}按计划推进负责项目，并完成阶段性评审与沟通。\n"
        f"- 关键事实、工时和交付物均已录入工作台。\n\n"
        f"## 风险与待协调事项\n"
        f"- 客户侧反馈和测试环境准备需要持续跟进。\n\n"
        f"## 下周计划\n"
        f"- 关闭本周遗留事项，推进下一阶段里程碑。"
    )


def _seed_weekly_reports(
    db: Session,
    users: dict[str, User],
    *,
    current_week: date,
) -> tuple[int, int]:
    business_keys = ("leader", "full", "opportunity", "personal", "newcomer")
    submitted_by_week = {
        0: {"leader", "full", "opportunity"},
        1: set(business_keys),
        2: {"leader", "full", "opportunity", "personal"},
        3: set(business_keys),
        4: {"leader", "full", "personal"},
    }
    report_count = 0
    for week_index in range(5):
        week = current_week - timedelta(weeks=week_index)
        for user_key in business_keys:
            if week_index == 0 and user_key == "newcomer":
                continue
            user = users[user_key]
            content = _report_content(user, week, current=week_index == 0)
            is_submitted = user_key in submitted_by_week[week_index]
            submitted_at = (
                _at(week + timedelta(days=4), 18) if is_submitted else None
            )
            leader = users["admin"] if user_key == "leader" else users["leader"]
            existing = db.scalar(
                select(WeeklyReport).where(
                    WeeklyReport.author_id == user.id,
                    WeeklyReport.week_start == week,
                )
            )
            report_id = (
                existing.id
                if existing
                else _demo_id("weekly-report", f"{week.isoformat()}:{user_key}")
            )
            _upsert(
                db,
                WeeklyReport,
                report_id,
                author_id=user.id,
                week_start=week,
                week_end=week + timedelta(days=6),
                content=(
                    content + "\n\n> 草稿：待补充客户确认结论。"
                    if week_index == 0 and user_key == "personal"
                    else content
                ),
                submitted_content=content if is_submitted else None,
                submitted_to_id=leader.id if is_submitted else None,
                generated_at=_at(week + timedelta(days=4), 17),
                generation_model="demo-seed-model",
                generation_usage={
                    "prompt_tokens": 620,
                    "completion_tokens": 280,
                    "total_tokens": 900,
                },
                submitted_at=submitted_at,
                submission_version=1 if is_submitted else 0,
                created_at=_at(week + timedelta(days=4), 17),
                updated_at=_at(week + timedelta(days=4), 18),
                revision=2 if is_submitted else 1,
            )
            report_count += 1

    summary_specs = (
        (
            "current",
            current_week,
            True,
            3,
            5,
            "# 解决方案部门周报\n\n"
            "## 本周总体概览\n"
            "重点商机进入方案确认与 POC 阶段，当前三人已提交个人周报。\n\n"
            "## 风险与待协调事项\n"
            "客户测试环境和脱敏语料交付需要团队负责人持续协调。\n\n"
            "## 提交说明\n"
            "本次为强制生成的演示总结，包含 3/5 位成员。",
        ),
        (
            "previous",
            current_week - timedelta(weeks=1),
            False,
            5,
            5,
            "# 解决方案部门周报\n\n"
            "## 本周总体概览\n"
            "团队完成全员周报提交，两个重点商机推进至新阶段。\n\n"
            "## 本周交付物\n"
            "完成总体架构、POC 评测方案与移动门户改造方案。\n\n"
            "## 提交说明\n"
            "本次汇总包含 5/5 位成员。",
        ),
    )
    for key, week, forced, submitted_count, expected_count, content in summary_specs:
        _upsert(
            db,
            TeamWeeklySummary,
            _demo_id("team-weekly-summary", key),
            week_start=week,
            week_end=week + timedelta(days=6),
            content=content,
            generated_by=users["leader"].id,
            forced=forced,
            submitted_count=submitted_count,
            expected_count=expected_count,
            generation_model="demo-seed-model",
            generation_usage={
                "prompt_tokens": 2100,
                "completion_tokens": 760,
                "total_tokens": 2860,
            },
            created_at=_at(week + timedelta(days=5), 10),
            updated_at=_at(week + timedelta(days=5), 10),
            revision=1,
        )
    return report_count, len(summary_specs)


def _seed_audit_events(
    db: Session,
    users: dict[str, User],
    projects: dict[str, Project],
    tasks: dict[str, Task],
    records: dict[str, WorkRecord],
    *,
    current_week: date,
) -> int:
    definitions = (
        (
            "permission-update",
            "user.permissions.update",
            "user",
            users["full"].id,
            users["root"].id,
            {"permissions": ["dashboard.opportunity.view", "projects.create"]},
        ),
        (
            "project-progress",
            "project.progress.record",
            "project_progress",
            _demo_id("project-progress", f"energy:{current_week.isoformat()}"),
            users["leader"].id,
            {"projectId": projects["energy"].id},
        ),
        (
            "task-transition",
            "task.transition",
            "task",
            tasks["bank_eval"].id,
            users["full"].id,
            {"status": "in_progress"},
        ),
        (
            "record-create",
            "work_record.create",
            "work_record",
            records["full_eval"].id,
            users["full"].id,
            {"minutes": 180, "deliverableCount": 1},
        ),
        (
            "report-submit",
            "weekly_report.submit",
            "weekly_report",
            _demo_id("weekly-report", f"{current_week.isoformat()}:full"),
            users["full"].id,
            {"weekStart": current_week.isoformat(), "submissionVersion": 1},
        ),
        (
            "team-summary",
            "team_weekly_summary.generate",
            "team_weekly_summary",
            _demo_id("team-weekly-summary", "current"),
            users["leader"].id,
            {"forced": True, "submittedCount": 3, "expectedCount": 5},
        ),
    )
    for index, (
        key,
        action,
        entity_type,
        entity_id,
        actor_id,
        detail,
    ) in enumerate(definitions):
        _upsert(
            db,
            AuditEvent,
            _demo_id("audit-event", key),
            request_id=f"demo-seed-{index + 1:02d}",
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_data=None,
            after_data=detail,
            result="success",
            detail={"seeded": True},
            client_ip="127.0.0.1",
            created_at=_at(current_week + timedelta(days=index % 5), 9 + index),
        )
    return len(definitions)


def seed_demo_data(
    db: Session,
    *,
    password: str,
    today: date | None = None,
) -> dict[str, Any]:
    if len(password) < 10:
        raise ValueError("演示账号密码至少需要 10 位")
    current_week = _week_start(today)
    users = _seed_users(db, password=password)
    permission_count = _seed_permissions(db, users)
    tags = _seed_tags(db, users)
    projects = _seed_projects(db, users, tags, current_week=current_week)
    tasks = _seed_tasks(db, users, projects, current_week=current_week)
    progress_count = _seed_progress(
        db,
        users,
        projects,
        current_week=current_week,
    )
    opportunity_count, opportunity_progress_count = _seed_opportunities(
        db,
        users,
        projects,
        current_week=current_week,
    )
    records, deliverable_count = _seed_work_records(
        db,
        users,
        projects,
        tasks,
        current_week=current_week,
    )
    report_count, summary_count = _seed_weekly_reports(
        db,
        users,
        current_week=current_week,
    )
    audit_count = _seed_audit_events(
        db,
        users,
        projects,
        tasks,
        records,
        current_week=current_week,
    )
    db.flush()
    return {
        "week_start": current_week,
        "users": len(users),
        "permissions": permission_count,
        "tags": len(tags),
        "projects": len(projects),
        "opportunities": opportunity_count,
        "tasks": len(tasks),
        "progress": progress_count,
        "opportunity_progress": opportunity_progress_count,
        "work_records": len(records),
        "deliverables": deliverable_count,
        "weekly_reports": report_count,
        "team_summaries": summary_count,
        "audit_events": audit_count,
        "login_names": list(DEMO_LOGIN_NAMES),
    }
