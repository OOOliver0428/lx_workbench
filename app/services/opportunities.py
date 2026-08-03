from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import (
    is_privileged,
    jsonable_snapshot,
    new_opportunity_code,
    normalize_name,
)
from app.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import (
    BusinessStage,
    Opportunity,
    OpportunityMember,
    OpportunityProgress,
    OpportunityStatus,
    PermissionKey,
    Project,
    ProjectMember,
    ProjectMemberRole,
    User,
    utc_now,
)
from app.schemas import (
    OpportunityConvertRequest,
    OpportunityCreate,
    OpportunityMemberOut,
    OpportunityOut,
    OpportunityProgressCreate,
)
from app.services import permissions as permission_service
from app.services import projects as project_service

STAGE_ORDER = tuple(stage.value for stage in BusinessStage)
CONVERTIBLE_STAGES = frozenset(
    STAGE_ORDER[STAGE_ORDER.index(BusinessStage.SOLUTION_EXCHANGE.value) :]
)
OPPORTUNITY_SNAPSHOT_FIELDS = (
    "id",
    "code",
    "name",
    "customer_name",
    "description",
    "owner_id",
    "status",
    "business_stage",
    "attention_status",
    "progress_percent",
    "linked_project_id",
    "project_linked_at",
    "revision",
)


def get_opportunity(
    db: Session,
    opportunity_id: str,
    *,
    include_deleted: bool = False,
) -> Opportunity:
    opportunity = db.get(Opportunity, opportunity_id)
    if not opportunity or (opportunity.deleted_at and not include_deleted):
        raise NotFoundError("OPPORTUNITY_NOT_FOUND", "商机不存在")
    return opportunity


def can_manage_opportunity(actor: User, opportunity: Opportunity) -> bool:
    return is_privileged(actor) or opportunity.owner_id == actor.id


def require_manage_opportunity(actor: User, opportunity: Opportunity) -> None:
    if not can_manage_opportunity(actor, opportunity):
        raise PermissionDeniedError("只有商机负责人、团队负责人或管理员可以修改商机")


def can_convert_opportunity(actor: User, opportunity: Opportunity) -> bool:
    return (
        can_manage_opportunity(actor, opportunity)
        and opportunity.linked_project_id is None
        and opportunity.status
        in {OpportunityStatus.ACTIVE.value, OpportunityStatus.WON.value}
        and opportunity.business_stage in CONVERTIBLE_STAGES
    )


def _active_users(db: Session, user_ids: set[str]) -> dict[str, User]:
    if not user_ids:
        return {}
    users = list(db.scalars(select(User).where(User.id.in_(user_ids))).all())
    valid = {
        user.id: user
        for user in users
        if user.is_active and user.role != "super_admin"
    }
    if len(valid) != len(user_ids):
        raise AppError("INVALID_OPPORTUNITY_MEMBER", "商机负责人或成员不存在或已停用")
    return valid


def _member_ids(db: Session, opportunity_id: str) -> list[str]:
    return list(
        db.scalars(
            select(OpportunityMember.user_id)
            .where(OpportunityMember.opportunity_id == opportunity_id)
            .order_by(OpportunityMember.added_at)
        ).all()
    )


def opportunity_out(
    db: Session,
    opportunity: Opportunity,
    actor: User,
) -> OpportunityOut:
    db.flush()
    payload = OpportunityOut.model_validate(opportunity)
    owner = db.get(User, opportunity.owner_id)
    payload.owner_display_name = owner.display_name if owner else "未知用户"
    payload.owner_avatar_key = owner.avatar_key if owner else None
    member_ids = _member_ids(db, opportunity.id)
    members = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(member_ids))).all()
    } if member_ids else {}
    payload.members = [
        OpportunityMemberOut(
            id=user_id,
            display_name=members[user_id].display_name,
            avatar_key=members[user_id].avatar_key,
        )
        for user_id in member_ids
        if user_id in members
    ]
    linked_project = (
        db.get(Project, opportunity.linked_project_id)
        if opportunity.linked_project_id
        else None
    )
    if linked_project and not linked_project.deleted_at:
        payload.linked_project_code = linked_project.code
        payload.linked_project_name = linked_project.name
        payload.linked_project_status = linked_project.status
    payload.can_manage = (
        permission_service.has_permission(
            db,
            actor,
            PermissionKey.DASHBOARD_OPPORTUNITY_PROGRESS,
        )
        and can_manage_opportunity(actor, opportunity)
    )
    payload.can_convert = (
        payload.can_manage
        and permission_service.has_permission(
            db,
            actor,
            PermissionKey.PROJECTS_CREATE,
        )
        and can_convert_opportunity(
            actor,
            opportunity,
        )
    )
    return payload


def list_opportunities(db: Session) -> list[Opportunity]:
    return list(
        db.scalars(
            select(Opportunity)
            .where(Opportunity.deleted_at.is_(None))
            .order_by(Opportunity.updated_at.desc(), Opportunity.name)
        ).all()
    )


def create_opportunity(
    db: Session,
    payload: OpportunityCreate,
    actor: User,
) -> Opportunity:
    owner = project_service.ensure_user(db, payload.owner_id or actor.id)
    requested_members = set(payload.member_ids) | {owner.id}
    members = _active_users(db, requested_members)
    opportunity = Opportunity(
        code=new_opportunity_code(),
        name=payload.name.strip(),
        normalized_name=normalize_name(payload.name),
        customer_name=(
            payload.customer_name.strip() if payload.customer_name else None
        ),
        description=payload.description.strip() if payload.description else None,
        owner_id=owner.id,
        created_by=actor.id,
        status=OpportunityStatus.ACTIVE.value,
        business_stage=BusinessStage.LEAD.value,
        progress_percent=0,
    )
    db.add(opportunity)
    db.flush()
    for user_id in requested_members:
        db.add(
            OpportunityMember(
                opportunity_id=opportunity.id,
                user_id=members[user_id].id,
                added_by=actor.id,
            )
        )
    record_audit(
        db,
        actor=actor,
        action="opportunity.create",
        entity_type="opportunity",
        entity_id=opportunity.id,
        after_data=jsonable_snapshot(opportunity, OPPORTUNITY_SNAPSHOT_FIELDS),
        detail={"memberIds": sorted(requested_members)},
    )
    return opportunity


def record_progress(
    db: Session,
    opportunity: Opportunity,
    payload: OpportunityProgressCreate,
    actor: User,
) -> OpportunityProgress:
    require_manage_opportunity(actor, opportunity)
    project_service.assert_revision(
        opportunity,
        payload.revision,
        entity_name="opportunity",
    )
    before = jsonable_snapshot(opportunity, OPPORTUNITY_SNAPSHOT_FIELDS)
    progress = OpportunityProgress(
        opportunity_id=opportunity.id,
        week_start=payload.week_start,
        business_stage=payload.business_stage.value,
        attention_status=payload.attention_status.value,
        progress_percent=payload.progress_percent,
        summary=payload.summary.strip(),
        output_summary=(
            payload.output_summary.strip() if payload.output_summary else None
        ),
        created_by=actor.id,
    )
    db.add(progress)
    opportunity.business_stage = payload.business_stage.value
    opportunity.attention_status = payload.attention_status.value
    opportunity.progress_percent = payload.progress_percent
    if payload.business_stage == BusinessStage.WON:
        opportunity.status = OpportunityStatus.WON.value
    elif opportunity.status == OpportunityStatus.WON.value:
        opportunity.status = OpportunityStatus.ACTIVE.value
    opportunity.revision += 1
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="opportunity.progress.record",
        entity_type="opportunity_progress",
        entity_id=progress.id,
        before_data=before,
        after_data=jsonable_snapshot(opportunity, OPPORTUNITY_SNAPSHOT_FIELDS),
        detail={"opportunityId": opportunity.id},
    )
    return progress


def convert_to_project(
    db: Session,
    opportunity: Opportunity,
    payload: OpportunityConvertRequest,
    actor: User,
) -> Project:
    require_manage_opportunity(actor, opportunity)
    project_service.assert_revision(
        opportunity,
        payload.revision,
        entity_name="opportunity",
    )
    if opportunity.linked_project_id:
        raise ConflictError(
            "OPPORTUNITY_ALREADY_LINKED",
            "该商机已经关联项目",
            {"project_id": opportunity.linked_project_id},
        )
    if opportunity.business_stage not in CONVERTIBLE_STAGES:
        raise ConflictError(
            "OPPORTUNITY_STAGE_NOT_CONVERTIBLE",
            "商机进入方案交流后才可以创建关联项目",
            {"business_stage": opportunity.business_stage},
        )
    if opportunity.status in {
        OpportunityStatus.LOST.value,
        OpportunityStatus.ARCHIVED.value,
    }:
        raise ConflictError(
            "OPPORTUNITY_STATUS_NOT_CONVERTIBLE",
            "已丢单或已归档商机不能创建关联项目",
        )

    before = jsonable_snapshot(opportunity, OPPORTUNITY_SNAPSHOT_FIELDS)
    project = project_service.create_project(db, payload.project, actor)
    db.flush()
    existing_project_members = {project.owner_id} | {
        user_id
        for user_id in db.scalars(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project.id
            )
        ).all()
    }
    for user_id in _member_ids(db, opportunity.id):
        if user_id in existing_project_members:
            continue
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=user_id,
                role=ProjectMemberRole.MEMBER.value,
                added_by=actor.id,
            )
        )
    opportunity.linked_project_id = project.id
    opportunity.project_linked_at = utc_now()
    opportunity.revision += 1
    db.flush()
    record_audit(
        db,
        actor=actor,
        action="opportunity.project.link",
        entity_type="opportunity",
        entity_id=opportunity.id,
        before_data=before,
        after_data=jsonable_snapshot(opportunity, OPPORTUNITY_SNAPSHOT_FIELDS),
        detail={"projectId": project.id},
    )
    return project
