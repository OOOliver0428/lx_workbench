from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import PermissionKey, User
from app.schemas import ProjectTagCreate, ProjectTagOut, ProjectTagUpdate
from app.services import permissions as permission_service
from app.services import tags as tag_service

router = APIRouter(prefix="/project-tags", tags=["project-tags"])


@router.get("", response_model=list[ProjectTagOut])
def list_tags(
    include_inactive: bool = False,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectTagOut]:
    permission_service.assert_any_permission(
        db,
        actor,
        (
            PermissionKey.PROJECTS_VIEW,
            PermissionKey.PROJECTS_MANAGE,
            PermissionKey.TAGS_MANAGE,
        ),
    )
    return [
        ProjectTagOut.model_validate(tag)
        for tag in tag_service.list_tags(db, include_inactive=include_inactive)
    ]


@router.post("", response_model=ProjectTagOut, status_code=201)
def create_tag(
    payload: ProjectTagCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ProjectTagOut:
    permission_service.assert_permission(db, actor, PermissionKey.TAGS_MANAGE)
    return ProjectTagOut.model_validate(tag_service.create_tag(db, payload, actor))


@router.patch("/{tag_id}", response_model=ProjectTagOut)
def update_tag(
    tag_id: str,
    payload: ProjectTagUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ProjectTagOut:
    permission_service.assert_permission(db, actor, PermissionKey.TAGS_MANAGE)
    tag = tag_service.get_tag(db, tag_id)
    return ProjectTagOut.model_validate(tag_service.update_tag(db, tag, payload, actor))
