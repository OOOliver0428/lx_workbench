from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import User
from app.presentation import public_admin_copy
from app.schemas import (
    ChangelogEntryCreate,
    ChangelogEntryOut,
    ChangelogEntryUpdate,
)
from app.services import changelog as changelog_service

router = APIRouter(prefix="/changelog", tags=["changelog"])


def _entry_out(entry, db: Session) -> ChangelogEntryOut:
    created_by = db.get(User, entry.created_by)
    updated_by = db.get(User, entry.updated_by)
    return ChangelogEntryOut(
        id=entry.id,
        occurred_at=entry.occurred_at,
        category=entry.category,
        title=public_admin_copy(entry.title),
        body=public_admin_copy(entry.body),
        created_by=entry.created_by,
        created_by_name=(
            public_admin_copy(created_by.display_name) if created_by else entry.created_by
        ),
        updated_by=entry.updated_by,
        updated_by_name=(
            public_admin_copy(updated_by.display_name) if updated_by else entry.updated_by
        ),
        revision=entry.revision,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("", response_model=list[ChangelogEntryOut])
def list_changelog_entries(
    limit: int = Query(default=200, ge=1, le=500),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[ChangelogEntryOut]:
    _ = actor
    return [
        _entry_out(entry, db)
        for entry in changelog_service.list_changelog_entries(db, limit=limit)
    ]


@router.post("", response_model=ChangelogEntryOut, status_code=201)
def create_changelog_entry(
    payload: ChangelogEntryCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ChangelogEntryOut:
    entry = changelog_service.create_changelog_entry(db, payload, actor)
    return _entry_out(entry, db)


@router.patch("/{entry_id}", response_model=ChangelogEntryOut)
def update_changelog_entry(
    entry_id: str,
    payload: ChangelogEntryUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ChangelogEntryOut:
    entry = changelog_service.get_changelog_entry(db, entry_id)
    entry = changelog_service.update_changelog_entry(db, entry, payload, actor)
    return _entry_out(entry, db)


@router.delete("/{entry_id}", status_code=204)
def delete_changelog_entry(
    entry_id: str,
    revision: int,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    entry = changelog_service.get_changelog_entry(db, entry_id)
    changelog_service.delete_changelog_entry(db, entry, revision=revision, actor=actor)
