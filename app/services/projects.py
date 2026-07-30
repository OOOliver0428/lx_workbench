from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import is_privileged, jsonable_snapshot, new_project_code, normalize_name
from app.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import (
    Deliverable,
    Project,
    ProjectAlias,
    ProjectMember,
    ProjectMemberRole,
    ProjectMerge,
    ProjectStatus,
    ProjectTag,
    ProjectTagAssignment,
    Task,
    User,
    UserRole,
    WorkRecord,
    utc_now,
)
from app.schemas import (
    DuplicateCandidate,
    ProjectCreate,
    ProjectMergePreview,
    ProjectMergeRequest,
    ProjectUpdate,
)

PROJECT_SNAPSHOT_FIELDS = (
    "id",
    "code",
    "name",
    "description",
    "status",
    "parent_project_id",
    "owner_id",
    "proposed_by",
    "approved_by",
    "approved_at",
    "rejected_reason",
    "merged_into_project_id",
    "planned_start_date",
    "planned_end_date",
    "revision",
)

PROJECT_TRANSITIONS: dict[str, set[str]] = {
    ProjectStatus.PENDING.value: {
        ProjectStatus.ACTIVE.value,
        ProjectStatus.REJECTED.value,
        ProjectStatus.ARCHIVED.value,
    },
    ProjectStatus.ACTIVE.value: {
        ProjectStatus.PAUSED.value,
        ProjectStatus.COMPLETED.value,
        ProjectStatus.ARCHIVED.value,
    },
    ProjectStatus.PAUSED.value: {
        ProjectStatus.ACTIVE.value,
        ProjectStatus.COMPLETED.value,
        ProjectStatus.ARCHIVED.value,
    },
    ProjectStatus.COMPLETED.value: {
        ProjectStatus.ACTIVE.value,
        ProjectStatus.ARCHIVED.value,
    },
    ProjectStatus.ARCHIVED.value: {
        ProjectStatus.ACTIVE.value,
        ProjectStatus.PAUSED.value,
        ProjectStatus.COMPLETED.value,
    },
    ProjectStatus.REJECTED.value: {ProjectStatus.PENDING.value},
    ProjectStatus.MERGED.value: set(),
}


def get_project(db: Session, project_id: str, *, include_deleted: bool = False) -> Project:
    project = db.get(Project, project_id)
    if not project or (project.deleted_at and not include_deleted):
        raise NotFoundError("PROJECT_NOT_FOUND", "项目不存在")
    return project


def ensure_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if (
        not user
        or not user.is_active
        or user.role == UserRole.SUPER_ADMIN.value
    ):
        raise AppError("INVALID_USER", "用户不存在或已停用")
    return user


def assert_revision(entity: object, expected: int, *, entity_name: str) -> None:
    actual = entity.revision
    if actual != expected:
        raise ConflictError(
            f"{entity_name.upper()}_REVISION_CONFLICT",
            f"{entity_name}已被其他用户修改",
            {"expected_revision": expected, "current_revision": actual},
        )


def can_manage_project(user: User, project: Project) -> bool:
    return is_privileged(user) or project.owner_id == user.id


def require_manage_project(user: User, project: Project) -> None:
    if not can_manage_project(user, project):
        raise PermissionDeniedError("只有项目负责人、团队负责人或管理员可以修改项目")


def _project_is_descendant(db: Session, candidate_id: str, ancestor_id: str) -> bool:
    current_id: str | None = candidate_id
    visited: set[str] = set()
    while current_id:
        if current_id == ancestor_id:
            return True
        if current_id in visited:
            raise AppError("PROJECT_HIERARCHY_CORRUPTED", "项目层级存在循环", status_code=500)
        visited.add(current_id)
        current = db.get(Project, current_id)
        current_id = current.parent_project_id if current else None
    return False


def ensure_valid_parent(db: Session, *, project_id: str | None, parent_id: str | None) -> None:
    if not parent_id:
        return
    parent = get_project(db, parent_id)
    if parent.status in {ProjectStatus.MERGED.value, ProjectStatus.REJECTED.value}:
        raise AppError("INVALID_PARENT_PROJECT", "不能选择已合并或已拒绝项目作为父项目")
    if project_id and (
        parent_id == project_id or _project_is_descendant(db, parent_id, project_id)
    ):
        raise AppError("PROJECT_HIERARCHY_CYCLE", "项目层级不能形成循环")


def _active_projects(db: Session, *, exclude_id: str | None = None) -> list[Project]:
    query = select(Project).where(
        Project.deleted_at.is_(None),
        Project.status != ProjectStatus.MERGED.value,
    )
    if exclude_id:
        query = query.where(Project.id != exclude_id)
    return list(db.scalars(query).all())


def duplicate_candidates(
    db: Session,
    name: str,
    *,
    exclude_id: str | None = None,
    threshold: float = 0.72,
) -> list[DuplicateCandidate]:
    normalized = normalize_name(name)
    candidates: list[DuplicateCandidate] = []
    projects = {project.id: project for project in _active_projects(db, exclude_id=exclude_id)}

    for project in projects.values():
        similarity = SequenceMatcher(None, normalized, project.normalized_name).ratio()
        if project.normalized_name == normalized or similarity >= threshold:
            candidates.append(
                DuplicateCandidate(
                    project_id=project.id,
                    code=project.code,
                    name=project.name,
                    matched_value=project.name,
                    match_type="exact_name"
                    if project.normalized_name == normalized
                    else "similar_name",
                    similarity=similarity,
                    status=project.status,
                )
            )

    alias_query = select(ProjectAlias).where(ProjectAlias.project_id.in_(projects))
    for alias in db.scalars(alias_query).all():
        similarity = SequenceMatcher(None, normalized, alias.normalized_value).ratio()
        if alias.normalized_value == normalized or similarity >= threshold:
            project = projects[alias.project_id]
            candidates.append(
                DuplicateCandidate(
                    project_id=project.id,
                    code=project.code,
                    name=project.name,
                    matched_value=alias.value,
                    match_type="exact_alias"
                    if alias.normalized_value == normalized
                    else "similar_alias",
                    similarity=similarity,
                    status=project.status,
                )
            )

    candidates.sort(key=lambda item: (-item.similarity, item.name))
    unique: dict[tuple[str, str], DuplicateCandidate] = {}
    for candidate in candidates:
        unique[(candidate.project_id, candidate.match_type)] = candidate
    return list(unique.values())


def ensure_name_available(db: Session, name: str, *, exclude_id: str | None = None) -> None:
    normalized = normalize_name(name)
    if not normalized:
        raise AppError("INVALID_PROJECT_NAME", "项目名称不能只包含空格或符号")
    project_query = select(Project.id).where(
        Project.normalized_name == normalized,
        Project.deleted_at.is_(None),
        Project.status != ProjectStatus.MERGED.value,
    )
    if exclude_id:
        project_query = project_query.where(Project.id != exclude_id)
    if db.scalar(project_query):
        raise ConflictError("PROJECT_NAME_CONFLICT", "已存在同名项目")
    alias_query = select(ProjectAlias.project_id).where(ProjectAlias.normalized_value == normalized)
    alias_project_id = db.scalar(alias_query)
    if alias_project_id and alias_project_id != exclude_id:
        raise ConflictError("PROJECT_ALIAS_CONFLICT", "该名称已被用作其他项目的别名")


def _ensure_tags(db: Session, tag_ids: Iterable[str]) -> list[ProjectTag]:
    ids = list(dict.fromkeys(tag_ids))
    if not ids:
        return []
    tags = list(
        db.scalars(
            select(ProjectTag).where(
                ProjectTag.id.in_(ids),
                ProjectTag.deleted_at.is_(None),
                ProjectTag.is_active.is_(True),
            )
        ).all()
    )
    if len(tags) != len(ids):
        raise AppError("INVALID_PROJECT_TAG", "包含不存在或已停用的项目标签")
    return tags


def _add_owner_membership(db: Session, project: Project, actor: User) -> None:
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == project.owner_id,
        )
    )
    if membership:
        membership.role = ProjectMemberRole.OWNER.value
        membership.left_at = None
        return
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=project.owner_id,
            role=ProjectMemberRole.OWNER.value,
            added_by=actor.id,
        )
    )


def create_project(db: Session, payload: ProjectCreate, actor: User) -> Project:
    ensure_name_available(db, payload.name)
    if (
        payload.planned_start_date
        and payload.planned_end_date
        and payload.planned_end_date < payload.planned_start_date
    ):
        raise AppError("INVALID_PROJECT_DATES", "项目结束日期不能早于开始日期")
    candidates = duplicate_candidates(db, payload.name)
    similar = [item for item in candidates if item.similarity >= 0.82]
    if similar and not payload.allow_similar_name:
        raise ConflictError(
            "SIMILAR_PROJECT_EXISTS",
            "发现疑似重复项目，请确认后再创建",
            {"candidates": [item.model_dump() for item in similar[:10]]},
        )

    ensure_valid_parent(db, project_id=None, parent_id=payload.parent_project_id)
    owner = ensure_user(db, payload.owner_id or actor.id)
    tags = _ensure_tags(db, payload.tag_ids)
    project = Project(
        code=new_project_code(),
        name=payload.name.strip(),
        normalized_name=normalize_name(payload.name),
        description=payload.description,
        parent_project_id=payload.parent_project_id,
        owner_id=owner.id,
        proposed_by=actor.id,
        planned_start_date=payload.planned_start_date,
        planned_end_date=payload.planned_end_date,
        status=ProjectStatus.PENDING.value,
    )
    db.add(project)
    db.flush()
    _add_owner_membership(db, project, actor)
    for tag in tags:
        db.add(ProjectTagAssignment(project_id=project.id, tag_id=tag.id, added_by=actor.id))
    record_audit(
        db,
        actor=actor,
        action="project.create_proposal",
        entity_type="project",
        entity_id=project.id,
        after_data=jsonable_snapshot(project, PROJECT_SNAPSHOT_FIELDS),
        detail={"tagIds": [tag.id for tag in tags]},
    )
    return project


def list_projects(
    db: Session,
    *,
    status: str | None = None,
    tag_id: str | None = None,
    parent_id: str | None = None,
    owner_id: str | None = None,
    query_text: str | None = None,
) -> list[Project]:
    query = select(Project).where(Project.deleted_at.is_(None))
    if status:
        query = query.where(Project.status == status)
    else:
        query = query.where(Project.status != ProjectStatus.MERGED.value)
    if tag_id:
        query = query.join(
            ProjectTagAssignment,
            ProjectTagAssignment.project_id == Project.id,
        ).where(ProjectTagAssignment.tag_id == tag_id)
    if parent_id:
        query = query.where(Project.parent_project_id == parent_id)
    if owner_id:
        query = query.where(Project.owner_id == owner_id)
    if query_text:
        normalized = normalize_name(query_text)
        alias_project_ids = select(ProjectAlias.project_id).where(
            ProjectAlias.normalized_value.contains(normalized)
        )
        query = query.where(
            or_(
                Project.normalized_name.contains(normalized),
                Project.code.ilike(f"%{query_text.strip()}%"),
                Project.id.in_(alias_project_ids),
            )
        )
    return list(db.scalars(query.order_by(Project.updated_at.desc()).limit(500)).all())


def update_project(db: Session, project: Project, payload: ProjectUpdate, actor: User) -> Project:
    require_manage_project(actor, project)
    assert_revision(project, payload.revision, entity_name="project")
    before = jsonable_snapshot(project, PROJECT_SNAPSHOT_FIELDS)
    fields = payload.model_fields_set - {"revision"}

    if "name" in fields and payload.name and payload.name.strip() != project.name:
        ensure_name_available(db, payload.name, exclude_id=project.id)
        old_name = project.name
        old_normalized = project.normalized_name
        project.name = payload.name.strip()
        project.normalized_name = normalize_name(payload.name)
        if old_normalized != project.normalized_name:
            existing = db.scalar(
                select(ProjectAlias).where(ProjectAlias.normalized_value == old_normalized)
            )
            if not existing:
                db.add(
                    ProjectAlias(
                        project_id=project.id,
                        value=old_name,
                        normalized_value=old_normalized,
                        source="rename",
                        created_by=actor.id,
                    )
                )

    if "parent_project_id" in fields:
        ensure_valid_parent(db, project_id=project.id, parent_id=payload.parent_project_id)
        project.parent_project_id = payload.parent_project_id
    if "description" in fields:
        project.description = payload.description
    if "planned_start_date" in fields:
        project.planned_start_date = payload.planned_start_date
    if "planned_end_date" in fields:
        project.planned_end_date = payload.planned_end_date
    if (
        project.planned_start_date
        and project.planned_end_date
        and project.planned_end_date < project.planned_start_date
    ):
        raise AppError("INVALID_PROJECT_DATES", "项目结束日期不能早于开始日期")
    if "owner_id" in fields and payload.owner_id and payload.owner_id != project.owner_id:
        ensure_user(db, payload.owner_id)
        previous_owner = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == project.owner_id,
            )
        )
        if previous_owner:
            previous_owner.role = ProjectMemberRole.MEMBER.value
        project.owner_id = payload.owner_id
        _add_owner_membership(db, project, actor)

    project.revision += 1
    project.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project.update",
        entity_type="project",
        entity_id=project.id,
        before_data=before,
        after_data=jsonable_snapshot(project, PROJECT_SNAPSHOT_FIELDS),
    )
    return project


def transition_project(
    db: Session,
    project: Project,
    *,
    target_status: str,
    revision: int,
    reason: str | None,
    actor: User,
) -> Project:
    require_manage_project(actor, project)
    assert_revision(project, revision, entity_name="project")
    if target_status not in PROJECT_TRANSITIONS.get(project.status, set()):
        raise AppError(
            "INVALID_PROJECT_TRANSITION",
            f"项目不能从 {project.status} 转为 {target_status}",
        )
    if target_status in {
        ProjectStatus.ACTIVE.value,
        ProjectStatus.REJECTED.value,
    } and not (is_privileged(actor) or project.owner_id == actor.id):
        raise PermissionDeniedError()
    if target_status == ProjectStatus.REJECTED.value and not reason:
        raise AppError("REJECT_REASON_REQUIRED", "驳回项目必须填写原因")
    if (
        target_status
        in {
            ProjectStatus.PAUSED.value,
            ProjectStatus.COMPLETED.value,
            ProjectStatus.ARCHIVED.value,
        }
        and not reason
    ):
        raise AppError("TRANSITION_REASON_REQUIRED", "该状态变更必须填写原因")

    before = jsonable_snapshot(project, PROJECT_SNAPSHOT_FIELDS)
    project.status = target_status
    if target_status == ProjectStatus.ACTIVE.value and not project.approved_at:
        project.approved_at = utc_now()
        project.approved_by = actor.id
        project.rejected_reason = None
    if target_status == ProjectStatus.REJECTED.value:
        project.rejected_reason = reason
    project.revision += 1
    project.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project.transition",
        entity_type="project",
        entity_id=project.id,
        before_data=before,
        after_data=jsonable_snapshot(project, PROJECT_SNAPSHOT_FIELDS),
        detail={"reason": reason},
    )
    return project


def add_alias(
    db: Session,
    project: Project,
    *,
    value: str,
    revision: int,
    actor: User,
) -> ProjectAlias:
    require_manage_project(actor, project)
    assert_revision(project, revision, entity_name="project")
    normalized = normalize_name(value)
    if not normalized or normalized == project.normalized_name:
        raise AppError("INVALID_ALIAS", "别名不能为空或与项目标准名称相同")
    ensure_name_available(db, value, exclude_id=project.id)
    alias = ProjectAlias(
        project_id=project.id,
        value=value.strip(),
        normalized_value=normalized,
        source="manual",
        created_by=actor.id,
    )
    db.add(alias)
    project.revision += 1
    project.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project.alias.add",
        entity_type="project",
        entity_id=project.id,
        detail={"alias": value.strip()},
    )
    db.flush()
    return alias


def add_project_tag(
    db: Session,
    project: Project,
    *,
    tag_id: str,
    revision: int,
    actor: User,
) -> None:
    require_manage_project(actor, project)
    assert_revision(project, revision, entity_name="project")
    _ensure_tags(db, [tag_id])
    existing = db.scalar(
        select(ProjectTagAssignment).where(
            ProjectTagAssignment.project_id == project.id,
            ProjectTagAssignment.tag_id == tag_id,
        )
    )
    if existing:
        raise ConflictError("PROJECT_TAG_EXISTS", "项目已经包含该标签")
    db.add(ProjectTagAssignment(project_id=project.id, tag_id=tag_id, added_by=actor.id))
    project.revision += 1
    project.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project.tag.add",
        entity_type="project",
        entity_id=project.id,
        detail={"tagId": tag_id},
    )


def remove_project_tag(
    db: Session,
    project: Project,
    *,
    tag_id: str,
    revision: int,
    actor: User,
) -> None:
    require_manage_project(actor, project)
    assert_revision(project, revision, entity_name="project")
    assignment = db.scalar(
        select(ProjectTagAssignment).where(
            ProjectTagAssignment.project_id == project.id,
            ProjectTagAssignment.tag_id == tag_id,
        )
    )
    if not assignment:
        raise NotFoundError("PROJECT_TAG_NOT_FOUND", "项目未包含该标签")
    db.delete(assignment)
    project.revision += 1
    project.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project.tag.remove",
        entity_type="project",
        entity_id=project.id,
        detail={"tagId": tag_id},
    )


def add_project_member(
    db: Session,
    project: Project,
    *,
    user_id: str,
    revision: int,
    actor: User,
) -> None:
    require_manage_project(actor, project)
    assert_revision(project, revision, entity_name="project")
    ensure_user(db, user_id)
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
        )
    )
    if membership and membership.left_at is None:
        raise ConflictError("PROJECT_MEMBER_EXISTS", "用户已经是项目成员")
    if membership:
        membership.left_at = None
        membership.joined_at = utc_now()
        membership.added_by = actor.id
    else:
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=user_id,
                role=ProjectMemberRole.MEMBER.value,
                added_by=actor.id,
            )
        )
    project.revision += 1
    project.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project.member.add",
        entity_type="project",
        entity_id=project.id,
        detail={"userId": user_id},
    )


def remove_project_member(
    db: Session,
    project: Project,
    *,
    user_id: str,
    revision: int,
    actor: User,
) -> None:
    require_manage_project(actor, project)
    assert_revision(project, revision, entity_name="project")
    if user_id == project.owner_id:
        raise AppError(
            "PROJECT_OWNER_REMOVAL_FORBIDDEN",
            "项目负责人不能直接移出项目，请先转移负责人",
        )
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
            ProjectMember.left_at.is_(None),
        )
    )
    if not membership:
        raise NotFoundError("PROJECT_MEMBER_NOT_FOUND", "项目中不存在该成员")

    membership.left_at = utc_now()
    project.revision += 1
    project.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project.member.remove",
        entity_type="project",
        entity_id=project.id,
        detail={"userId": user_id},
    )


def merge_preview(db: Session, source: Project, target: Project) -> ProjectMergePreview:
    if source.id == target.id:
        raise AppError("INVALID_PROJECT_MERGE", "不能合并项目自身")
    if _project_is_descendant(db, source.id, target.id) or _project_is_descendant(
        db, target.id, source.id
    ):
        raise AppError("ANCESTOR_MERGE_FORBIDDEN", "父子项目之间不能直接合并")

    source_members = set(
        db.scalars(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == source.id,
                ProjectMember.left_at.is_(None),
            )
        ).all()
    )
    target_members = set(
        db.scalars(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == target.id,
                ProjectMember.left_at.is_(None),
            )
        ).all()
    )
    source_tags = set(
        db.scalars(
            select(ProjectTagAssignment.tag_id).where(ProjectTagAssignment.project_id == source.id)
        ).all()
    )
    target_tags = set(
        db.scalars(
            select(ProjectTagAssignment.tag_id).where(ProjectTagAssignment.project_id == target.id)
        ).all()
    )
    aliases = list(
        db.scalars(select(ProjectAlias.value).where(ProjectAlias.project_id == source.id)).all()
    )
    aliases.insert(0, source.name)
    return ProjectMergePreview(
        source_project_id=source.id,
        target_project_id=target.id,
        source_name=source.name,
        target_name=target.name,
        task_count=db.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == source.id, Task.deleted_at.is_(None)
            )
        )
        or 0,
        work_record_count=db.scalar(
            select(func.count(WorkRecord.id)).where(
                WorkRecord.project_id == source.id,
                WorkRecord.deleted_at.is_(None),
            )
        )
        or 0,
        deliverable_count=db.scalar(
            select(func.count(Deliverable.id)).where(
                Deliverable.project_id == source.id,
                Deliverable.deleted_at.is_(None),
            )
        )
        or 0,
        child_project_count=db.scalar(
            select(func.count(Project.id)).where(
                Project.parent_project_id == source.id,
                Project.deleted_at.is_(None),
            )
        )
        or 0,
        new_member_count=len(source_members - target_members),
        new_tag_count=len(source_tags - target_tags),
        aliases_to_move=list(dict.fromkeys(aliases)),
    )


def merge_projects(
    db: Session,
    source: Project,
    payload: ProjectMergeRequest,
    actor: User,
) -> ProjectMerge:
    if not is_privileged(actor):
        raise PermissionDeniedError("只有团队负责人或管理员可以合并项目")
    target = get_project(db, payload.target_project_id)
    assert_revision(source, payload.source_revision, entity_name="source_project")
    assert_revision(target, payload.target_revision, entity_name="target_project")
    if source.status == ProjectStatus.MERGED.value or target.status == ProjectStatus.MERGED.value:
        raise AppError("PROJECT_ALREADY_MERGED", "来源或目标项目已经被合并")
    preview = merge_preview(db, source, target)
    source_snapshot = jsonable_snapshot(source, PROJECT_SNAPSHOT_FIELDS)
    target_snapshot = jsonable_snapshot(target, PROJECT_SNAPSHOT_FIELDS)

    now = utc_now()
    db.execute(
        update(Task)
        .where(Task.project_id == source.id)
        .values(
            project_id=target.id,
            revision=Task.revision + 1,
            updated_at=now,
        )
    )
    db.execute(
        update(WorkRecord)
        .where(WorkRecord.project_id == source.id)
        .values(
            project_id=target.id,
            revision=WorkRecord.revision + 1,
            updated_at=now,
        )
    )
    db.execute(
        update(Deliverable)
        .where(Deliverable.project_id == source.id)
        .values(
            project_id=target.id,
            revision=Deliverable.revision + 1,
            updated_at=now,
        )
    )
    db.execute(
        update(Project)
        .where(Project.parent_project_id == source.id)
        .values(parent_project_id=target.id, revision=Project.revision + 1, updated_at=utc_now())
    )

    target_members = {
        member.user_id: member
        for member in db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == target.id)
        ).all()
    }
    for member in db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == source.id,
            ProjectMember.left_at.is_(None),
        )
    ).all():
        target_member = target_members.get(member.user_id)
        if target_member:
            if target_member.left_at is not None:
                target_member.left_at = None
                target_member.joined_at = now
                target_member.added_by = actor.id
        else:
            db.add(
                ProjectMember(
                    project_id=target.id,
                    user_id=member.user_id,
                    role=(
                        ProjectMemberRole.OWNER.value
                        if member.user_id == target.owner_id
                        else ProjectMemberRole.MEMBER.value
                    ),
                    added_by=actor.id,
                )
            )

    target_tag_ids = set(
        db.scalars(
            select(ProjectTagAssignment.tag_id).where(ProjectTagAssignment.project_id == target.id)
        ).all()
    )
    for tag_id in db.scalars(
        select(ProjectTagAssignment.tag_id).where(ProjectTagAssignment.project_id == source.id)
    ).all():
        if tag_id not in target_tag_ids:
            db.add(ProjectTagAssignment(project_id=target.id, tag_id=tag_id, added_by=actor.id))

    existing_target_aliases = set(
        db.scalars(
            select(ProjectAlias.normalized_value).where(ProjectAlias.project_id == target.id)
        ).all()
    )
    for alias in db.scalars(select(ProjectAlias).where(ProjectAlias.project_id == source.id)).all():
        if alias.normalized_value not in existing_target_aliases:
            alias.project_id = target.id
            alias.source = "merge"
            existing_target_aliases.add(alias.normalized_value)
        else:
            db.delete(alias)
    if (
        source.normalized_name != target.normalized_name
        and source.normalized_name not in existing_target_aliases
    ):
        db.add(
            ProjectAlias(
                project_id=target.id,
                value=source.name,
                normalized_value=source.normalized_name,
                source="merge",
                created_by=actor.id,
            )
        )

    source.status = ProjectStatus.MERGED.value
    source.merged_into_project_id = target.id
    source.revision += 1
    source.updated_at = utc_now()
    target.revision += 1
    target.updated_at = utc_now()
    merge = ProjectMerge(
        source_project_id=source.id,
        target_project_id=target.id,
        reason=payload.reason,
        moved_counts={
            "task_count": preview.task_count,
            "work_record_count": preview.work_record_count,
            "deliverable_count": preview.deliverable_count,
            "child_project_count": preview.child_project_count,
            "member_count": preview.new_member_count,
            "tag_count": preview.new_tag_count,
        },
        source_snapshot=source_snapshot,
        target_snapshot=target_snapshot,
        merged_by=actor.id,
    )
    db.add(merge)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="project.merge",
        entity_type="project",
        entity_id=source.id,
        before_data=source_snapshot,
        after_data=jsonable_snapshot(source, PROJECT_SNAPSHOT_FIELDS),
        detail={"target_project_id": target.id, "reason": payload.reason},
    )
    return merge
