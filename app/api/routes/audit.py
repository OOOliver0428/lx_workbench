from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domain import is_super_admin
from app.errors import PermissionDeniedError
from app.models import AuditEvent, PermissionKey, User, UserRole
from app.schemas import AuditEventOut
from app.services import permissions as permission_service

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventOut])
def list_audit_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[AuditEventOut]:
    permission_service.assert_permission(db, actor, PermissionKey.AUDIT_VIEW)
    query = select(AuditEvent)
    if not is_super_admin(actor):
        if entity_type == "work_record":
            raise PermissionDeniedError("当前账号无权查看工作记录审计详情")
        super_admin_ids = select(User.id).where(
            User.role == UserRole.SUPER_ADMIN.value
        )
        query = query.where(
            AuditEvent.entity_type != "work_record",
            or_(
                AuditEvent.actor_id.is_(None),
                AuditEvent.actor_id.not_in(super_admin_ids),
            ),
        )
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditEvent.entity_id == entity_id)
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return [AuditEventOut.model_validate(row) for row in rows]
