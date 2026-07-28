from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_privileged_read
from app.domain import is_super_admin
from app.errors import PermissionDeniedError
from app.models import AuditEvent, User
from app.schemas import AuditEventOut

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventOut])
def list_audit_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require_privileged_read),
    db: Session = Depends(get_db),
) -> list[AuditEventOut]:
    query = select(AuditEvent)
    if not is_super_admin(actor):
        if entity_type == "work_record":
            raise PermissionDeniedError("仅超级管理员可以查看工作记录审计详情")
        query = query.where(AuditEvent.entity_type != "work_record")
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditEvent.entity_id == entity_id)
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return [AuditEventOut.model_validate(row) for row in rows]
