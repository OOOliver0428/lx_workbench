from __future__ import annotations

import re
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


def normalize_content(category: str, title: str, body: str) -> tuple[str, str]:
    title, body = title.strip(), body.strip()
    if category == "release":
        if len(title) > 80 or not re.fullmatch(
            r"[vV]?\d+(?:\.\d+){1,3}(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", title
        ):
            raise AppError("CHANGELOG_VERSION_INVALID", "请填写有效版本号，例如 0.3.1")
        return "v" + title.lstrip("vV"), ""
    if not title or not body:
        raise AppError("CHANGELOG_CONTENT_REQUIRED", "普通更新日志必须填写标题和说明")
    return title, body


def require_super_admin(actor: User) -> None:
    if not is_super_admin(actor):
        raise PermissionDeniedError("当前账号无权维护更新日志")


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
    title, body = normalize_content(payload.category.value, payload.title, payload.body)
    entry = ChangelogEntry(
        occurred_at=payload.occurred_at,
        category=payload.category.value,
        title=title,
        body=body,
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
    category = payload.category.value if payload.category is not None else entry.category
    title, body = normalize_content(
        category,
        payload.title if payload.title is not None else entry.title,
        payload.body if payload.body is not None else entry.body,
    )
    before = {
        field: getattr(entry, field).isoformat()
        if isinstance(getattr(entry, field), datetime)
        else getattr(entry, field)
        for field in SNAPSHOT_FIELDS
    }
    if payload.occurred_at is not None:
        entry.occurred_at = payload.occurred_at
    entry.category = category
    entry.title = title
    entry.body = body
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
