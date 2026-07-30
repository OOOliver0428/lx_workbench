from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import normalize_name
from app.errors import ConflictError, NotFoundError
from app.models import ProjectTag, User, utc_now
from app.schemas import ProjectTagCreate, ProjectTagUpdate
from app.services.projects import assert_revision


def get_tag(db: Session, tag_id: str) -> ProjectTag:
    tag = db.get(ProjectTag, tag_id)
    if not tag or tag.deleted_at:
        raise NotFoundError("PROJECT_TAG_NOT_FOUND", "项目标签不存在")
    return tag


def list_tags(db: Session, *, include_inactive: bool = False) -> list[ProjectTag]:
    query = select(ProjectTag).where(ProjectTag.deleted_at.is_(None))
    if not include_inactive:
        query = query.where(ProjectTag.is_active.is_(True))
    return list(db.scalars(query.order_by(ProjectTag.sort_order, ProjectTag.name)).all())


def create_tag(db: Session, payload: ProjectTagCreate, actor: User) -> ProjectTag:
    normalized = normalize_name(payload.name)
    if db.scalar(select(ProjectTag.id).where(ProjectTag.normalized_name == normalized)):
        raise ConflictError("PROJECT_TAG_NAME_CONFLICT", "项目标签已经存在")
    tag = ProjectTag(
        name=payload.name.strip(),
        normalized_name=normalized,
        description=payload.description,
        color=payload.color,
        sort_order=payload.sort_order,
    )
    db.add(tag)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="project_tag.create",
        entity_type="project_tag",
        entity_id=tag.id,
        after_data={
            "name": tag.name,
            "description": tag.description,
            "color": tag.color,
            "sortOrder": tag.sort_order,
        },
    )
    return tag


def update_tag(
    db: Session,
    tag: ProjectTag,
    payload: ProjectTagUpdate,
    actor: User,
) -> ProjectTag:
    assert_revision(tag, payload.revision, entity_name="project_tag")
    before = {
        "name": tag.name,
        "description": tag.description,
        "color": tag.color,
        "sortOrder": tag.sort_order,
        "isActive": tag.is_active,
        "revision": tag.revision,
    }
    fields = payload.model_fields_set - {"revision"}
    if "name" in fields and payload.name:
        normalized = normalize_name(payload.name)
        conflict = db.scalar(
            select(ProjectTag.id).where(
                ProjectTag.normalized_name == normalized,
                ProjectTag.id != tag.id,
            )
        )
        if conflict:
            raise ConflictError("PROJECT_TAG_NAME_CONFLICT", "项目标签已经存在")
        tag.name = payload.name.strip()
        tag.normalized_name = normalized
    for field in ("description", "color", "sort_order", "is_active"):
        if field in fields:
            setattr(tag, field, getattr(payload, field))
    tag.revision += 1
    tag.updated_at = utc_now()
    record_audit(
        db,
        actor=actor,
        action="project_tag.update",
        entity_type="project_tag",
        entity_id=tag.id,
        before_data=before,
        after_data={
            "name": tag.name,
            "description": tag.description,
            "color": tag.color,
            "sortOrder": tag.sort_order,
            "isActive": tag.is_active,
            "revision": tag.revision,
        },
    )
    return tag
