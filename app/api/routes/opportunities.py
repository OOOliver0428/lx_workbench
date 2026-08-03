from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.models import PermissionKey, User
from app.schemas import (
    OpportunityConversionOut,
    OpportunityConvertRequest,
    OpportunityCreate,
    OpportunityOut,
    OpportunityProgressCreate,
    OpportunityProgressOut,
)
from app.serializers import project_detail
from app.services import opportunities as opportunity_service
from app.services import permissions as permission_service

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityOut])
def list_opportunities(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[OpportunityOut]:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_OPPORTUNITY_VIEW,
        "当前账号无权查看商机",
    )
    return [
        opportunity_service.opportunity_out(db, opportunity, actor)
        for opportunity in opportunity_service.list_opportunities(db)
    ]


@router.post("", response_model=OpportunityOut, status_code=201)
def create_opportunity(
    payload: OpportunityCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> OpportunityOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_OPPORTUNITY_CREATE,
    )
    opportunity = opportunity_service.create_opportunity(db, payload, actor)
    return opportunity_service.opportunity_out(db, opportunity, actor)


@router.get("/{opportunity_id}", response_model=OpportunityOut)
def get_opportunity(
    opportunity_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> OpportunityOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_OPPORTUNITY_VIEW,
        "当前账号无权查看商机",
    )
    return opportunity_service.opportunity_out(
        db,
        opportunity_service.get_opportunity(db, opportunity_id),
        actor,
    )


@router.post(
    "/{opportunity_id}/progress",
    response_model=OpportunityProgressOut,
    status_code=201,
)
def record_progress(
    opportunity_id: str,
    payload: OpportunityProgressCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> OpportunityProgressOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS,
    )
    progress = opportunity_service.record_progress(
        db,
        opportunity_service.get_opportunity(db, opportunity_id),
        payload,
        actor,
    )
    return OpportunityProgressOut.model_validate(progress)


@router.post(
    "/{opportunity_id}/convert-to-project",
    response_model=OpportunityConversionOut,
    status_code=201,
)
def convert_to_project(
    opportunity_id: str,
    payload: OpportunityConvertRequest,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> OpportunityConversionOut:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS,
    )
    permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_CREATE)
    opportunity = opportunity_service.get_opportunity(db, opportunity_id)
    project = opportunity_service.convert_to_project(
        db,
        opportunity,
        payload,
        actor,
    )
    return OpportunityConversionOut(
        opportunity_id=opportunity.id,
        opportunity_revision=opportunity.revision,
        project=project_detail(db, project),
    )
