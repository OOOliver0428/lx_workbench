from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_admin
from app.models import User
from app.schemas import ProjectTagCreate, ProjectTagOut, ProjectTagUpdate
from app.services import tags as tag_service

router = APIRouter(prefix="/project-tags", tags=["project-tags"])


@router.get("", response_model=list[ProjectTagOut])
def list_tags(
    include_inactive: bool = False,
    _actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectTagOut]:
    return [
        ProjectTagOut.model_validate(tag)
        for tag in tag_service.list_tags(db, include_inactive=include_inactive)
    ]


@router.post("", response_model=ProjectTagOut, status_code=201)
def create_tag(
    payload: ProjectTagCreate,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProjectTagOut:
    return ProjectTagOut.model_validate(tag_service.create_tag(db, payload, actor))


@router.patch("/{tag_id}", response_model=ProjectTagOut)
def update_tag(
    tag_id: str,
    payload: ProjectTagUpdate,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProjectTagOut:
    tag = tag_service.get_tag(db, tag_id)
    return ProjectTagOut.model_validate(tag_service.update_tag(db, tag, payload, actor))
