from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import PermissionKey, User
from app.schemas import (
    DuplicateCandidate,
    ProjectAliasCreate,
    ProjectAliasOut,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMergeOut,
    ProjectMergePreview,
    ProjectMergeRequest,
    ProjectOut,
    ProjectProgressCreate,
    ProjectProgressOut,
    ProjectSummaryOut,
    ProjectTagAssign,
    ProjectTransition,
    ProjectUpdate,
)
from app.serializers import project_detail, project_summary
from app.services import dashboard as dashboard_service
from app.services import permissions as permission_service
from app.services import projects as project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummaryOut])
def list_projects(
    status: str | None = None,
    tag_id: str | None = None,
    parent_id: str | None = None,
    owner_id: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[ProjectSummaryOut]:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_VIEW)
    rows = project_service.list_projects(
        db,
        status=status,
        tag_id=tag_id,
        parent_id=parent_id,
        owner_id=owner_id,
        query_text=q,
    )
    return [project_summary(db, row) for row in rows]


@router.get("/duplicate-candidates", response_model=list[DuplicateCandidate])
def find_duplicate_candidates(
    name: str = Query(min_length=1, max_length=200),
    exclude_id: str | None = None,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[DuplicateCandidate]:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_VIEW)
    return project_service.duplicate_candidates(db, name, exclude_id=exclude_id)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectOut:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_CREATE)
    return project_detail(db, project_service.create_project(db, payload, actor))


@router.post(
    "/{project_id}/progress",
    response_model=ProjectProgressOut,
    status_code=201,
)
def record_project_progress(
    project_id: str,
    payload: ProjectProgressCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectProgressOut:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    progress = dashboard_service.record_project_progress(
        db,
        project_service.get_project(db, project_id),
        payload,
        actor,
    )
    return ProjectProgressOut.model_validate(progress)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectOut:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_VIEW)
    return project_detail(db, project_service.get_project(db, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectOut:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    project = project_service.get_project(db, project_id)
    return project_detail(db, project_service.update_project(db, project, payload, actor))


@router.post("/{project_id}/transition", response_model=ProjectOut)
def transition_project(
    project_id: str,
    payload: ProjectTransition,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectOut:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    project = project_service.get_project(db, project_id)
    result = project_service.transition_project(
        db,
        project,
        target_status=payload.status.value,
        revision=payload.revision,
        reason=payload.reason,
        actor=actor,
    )
    return project_detail(db, result)


@router.post("/{project_id}/aliases", response_model=ProjectAliasOut, status_code=201)
def add_alias(
    project_id: str,
    payload: ProjectAliasCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectAliasOut:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    project = project_service.get_project(db, project_id)
    return ProjectAliasOut.model_validate(
        project_service.add_alias(
            db,
            project,
            value=payload.value,
            revision=payload.revision,
            actor=actor,
        )
    )


@router.post("/{project_id}/tags", status_code=204)
def add_tag(
    project_id: str,
    payload: ProjectTagAssign,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    project_service.add_project_tag(
        db,
        project_service.get_project(db, project_id),
        tag_id=payload.tag_id,
        revision=payload.revision,
        actor=actor,
    )


@router.delete("/{project_id}/tags/{tag_id}", status_code=204)
def remove_tag(
    project_id: str,
    tag_id: str,
    revision: int = Query(ge=1),
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    project_service.remove_project_tag(
        db,
        project_service.get_project(db, project_id),
        tag_id=tag_id,
        revision=revision,
        actor=actor,
    )


@router.post("/{project_id}/members", status_code=204)
def add_member(
    project_id: str,
    payload: ProjectMemberAdd,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    project_service.add_project_member(
        db,
        project_service.get_project(db, project_id),
        user_id=payload.user_id,
        revision=payload.revision,
        actor=actor,
    )


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    project_id: str,
    user_id: str,
    revision: int = Query(ge=1),
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    project_service.remove_project_member(
        db,
        project_service.get_project(db, project_id),
        user_id=user_id,
        revision=revision,
        actor=actor,
    )


@router.get("/{project_id}/merge-preview", response_model=ProjectMergePreview)
def preview_merge(
    project_id: str,
    target_project_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectMergePreview:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_VIEW)
    return project_service.merge_preview(
        db,
        project_service.get_project(db, project_id),
        project_service.get_project(db, target_project_id),
    )


@router.post("/{project_id}/merge", response_model=ProjectMergeOut)
def merge_projects(
    project_id: str,
    payload: ProjectMergeRequest,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> ProjectMergeOut:
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_EDIT)
    merge = project_service.merge_projects(
        db,
        project_service.get_project(db, project_id),
        payload,
        actor,
    )
    return ProjectMergeOut(
        merge_id=merge.id,
        source_project_id=merge.source_project_id,
        target_project_id=merge.target_project_id,
        moved_counts=merge.moved_counts,
    )
