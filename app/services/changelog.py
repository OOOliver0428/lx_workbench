from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import is_super_admin
from app.errors import AppError, NotFoundError, PermissionDeniedError
from app.models import ChangelogEntry, User, utc_now
from app.schemas import ChangelogEntryCreate, ChangelogEntryUpdate
from app.services.projects import assert_revision

SNAPSHOT_FIELDS = (
    "occurred_at",
    "category",
    "title",
    "body",
)


def require_super_admin(actor: User) -> None:
    if not is_super_admin(actor):
        raise PermissionDeniedError("仅超级管理员可维护更新日志")


def get_changelog_entry(db: Session, entry_id: str) -> ChangelogEntry:
    entry = db.get(ChangelogEntry, entry_id)
    if not entry or entry.deleted_at:
        raise NotFoundError("CHANGELOG_ENTRY_NOT_FOUND", "更新日志条目不存在")
    return entry


def list_changelog_entries(db: Session, *, limit: int = 200) -> list[ChangelogEntry]:
    query = (
        select(ChangelogEntry)
        .where(ChangelogEntry.deleted_at.is_(None))
        .order_by(ChangelogEntry.occurred_at.desc(), ChangelogEntry.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    return list(db.scalars(query).all())


def create_changelog_entry(
    db: Session,
    payload: ChangelogEntryCreate,
    actor: User,
) -> ChangelogEntry:
    require_super_admin(actor)
    now = utc_now()
    entry = ChangelogEntry(
        occurred_at=payload.occurred_at,
        category=payload.category.value,
        title=payload.title,
        body=payload.body,
        created_by=actor.id,
        updated_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(entry)
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="changelog.create",
        entity_type="changelog_entry",
        entity_id=entry.id,
        after_data={
            "category": entry.category,
            "title": entry.title,
            "occurred_at": entry.occurred_at.isoformat(),
        },
    )
    return entry


def update_changelog_entry(
    db: Session,
    entry: ChangelogEntry,
    payload: ChangelogEntryUpdate,
    actor: User,
) -> ChangelogEntry:
    require_super_admin(actor)
    assert_revision(entry, payload.revision, entity_name="changelog_entry")
    before = {
        field: getattr(entry, field).isoformat()
        if isinstance(getattr(entry, field), datetime)
        else getattr(entry, field)
        for field in SNAPSHOT_FIELDS
    }
    if payload.occurred_at is not None:
        entry.occurred_at = payload.occurred_at
    if payload.category is not None:
        entry.category = payload.category.value
    if payload.title is not None:
        entry.title = payload.title
    if payload.body is not None:
        entry.body = payload.body
    entry.updated_by = actor.id
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="changelog.update",
        entity_type="changelog_entry",
        entity_id=entry.id,
        before_data=before,
        after_data={
            "category": entry.category,
            "title": entry.title,
            "occurred_at": entry.occurred_at.isoformat(),
        },
    )
    return entry


def delete_changelog_entry(
    db: Session,
    entry: ChangelogEntry,
    *,
    revision: int,
    actor: User,
) -> None:
    require_super_admin(actor)
    assert_revision(entry, revision, entity_name="changelog_entry")
    if entry.deleted_at:
        raise AppError("CHANGELOG_ENTRY_DELETED", "更新日志条目已删除", status_code=409)
    entry.deleted_at = utc_now()
    entry.deleted_by = actor.id
    entry.updated_by = actor.id
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="changelog.delete",
        entity_type="changelog_entry",
        entity_id=entry.id,
        before_data={"title": entry.title, "category": entry.category},
    )
