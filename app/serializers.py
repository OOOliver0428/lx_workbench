from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Deliverable,
    DepartmentWork,
    Project,
    ProjectAlias,
    ProjectMember,
    ProjectTag,
    ProjectTagAssignment,
    Task,
    TaskCollaborator,
    User,
    UserRole,
    WorkRecord,
)
from app.schemas import (
    DeliverableOut,
    ProjectAliasOut,
    ProjectMemberOut,
    ProjectOut,
    ProjectSummaryOut,
    ProjectTagOut,
    TaskOut,
    WorkRecordOut,
)


def project_tags(db: Session, project_id: str) -> list[ProjectTagOut]:
    rows = db.scalars(
        select(ProjectTag)
        .join(ProjectTagAssignment, ProjectTagAssignment.tag_id == ProjectTag.id)
        .where(
            ProjectTagAssignment.project_id == project_id,
            ProjectTag.deleted_at.is_(None),
        )
        .order_by(ProjectTag.sort_order, ProjectTag.name)
    ).all()
    return [ProjectTagOut.model_validate(row) for row in rows]


def project_summary(db: Session, project: Project) -> ProjectSummaryOut:
    db.flush()
    payload = ProjectSummaryOut.model_validate(project)
    owner = db.get(User, project.owner_id)
    owner_is_visible = bool(
        owner and owner.role != UserRole.SUPER_ADMIN.value
    )
    payload.owner_display_name = (
        owner.display_name if owner and owner_is_visible else "未知用户"
    )
    payload.owner_avatar_key = owner.avatar_key if owner and owner_is_visible else None
    payload.tags = project_tags(db, project.id)
    return payload


def project_detail(db: Session, project: Project) -> ProjectOut:
    db.flush()
    payload = ProjectOut.model_validate(project)
    owner = db.get(User, project.owner_id)
    owner_is_visible = bool(
        owner and owner.role != UserRole.SUPER_ADMIN.value
    )
    payload.owner_display_name = (
        owner.display_name if owner and owner_is_visible else "未知用户"
    )
    payload.owner_avatar_key = owner.avatar_key if owner and owner_is_visible else None
    payload.tags = project_tags(db, project.id)
    payload.aliases = [
        ProjectAliasOut.model_validate(row)
        for row in db.scalars(
            select(ProjectAlias)
            .where(ProjectAlias.project_id == project.id)
            .order_by(ProjectAlias.created_at)
        ).all()
    ]
    member_rows = db.execute(
        select(ProjectMember, User.display_name, User.avatar_key)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == project.id,
            User.role != UserRole.SUPER_ADMIN.value,
        )
        .order_by(ProjectMember.joined_at)
    ).all()
    payload.members = [
        ProjectMemberOut(
            user_id=member.user_id,
            display_name=display_name,
            avatar_key=avatar_key,
            role=member.role,
            joined_at=member.joined_at,
            left_at=member.left_at,
        )
        for member, display_name, avatar_key in member_rows
    ]
    return payload


def task_out(db: Session, task: Task) -> TaskOut:
    db.flush()
    payload = TaskOut.model_validate(task)
    payload.collaborator_ids = list(
        db.scalars(
            select(TaskCollaborator.user_id)
            .where(TaskCollaborator.task_id == task.id)
            .order_by(TaskCollaborator.added_at)
        ).all()
    )
    return payload


def deliverables_for_record(db: Session, record_id: str) -> list[DeliverableOut]:
    rows = db.scalars(
        select(Deliverable)
        .where(
            Deliverable.work_record_id == record_id,
            Deliverable.deleted_at.is_(None),
        )
        .order_by(Deliverable.created_at)
    ).all()
    return [DeliverableOut.model_validate(row) for row in rows]


def work_record_out(db: Session, record: WorkRecord) -> WorkRecordOut:
    db.flush()
    payload = WorkRecordOut.model_validate(record)
    author = db.get(User, record.author_id)
    project = db.get(Project, record.project_id) if record.project_id else None
    department_work = (
        db.get(DepartmentWork, record.department_work_id)
        if record.department_work_id
        else None
    )
    task = db.get(Task, record.task_id) if record.task_id else None
    last_editor = (
        author
        if record.last_edited_by == record.author_id
        else db.get(User, record.last_edited_by)
    )
    payload.author_display_name = author.display_name if author else "未知用户"
    payload.author_avatar_key = author.avatar_key if author else None
    payload.project_name = project.name if project else None
    payload.department_work_name = department_work.name if department_work else None
    if project:
        payload.source_type = "project"
        payload.source_id = project.id
        payload.source_name = project.name
    elif department_work:
        payload.source_type = "department_work"
        payload.source_id = department_work.id
        payload.source_name = department_work.name
    else:
        payload.source_type = None
        payload.source_id = None
        payload.source_name = None
    payload.task_title = task.title if task else None
    payload.last_editor_display_name = (
        last_editor.display_name if last_editor else "未知用户"
    )
    payload.last_editor_avatar_key = last_editor.avatar_key if last_editor else None
    payload.deliverables = deliverables_for_record(db, record.id)
    return payload
