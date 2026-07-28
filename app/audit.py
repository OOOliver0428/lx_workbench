from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def record_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    request_id: str | None = None,
    client_ip: str | None = None,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    result: str = "success",
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id or db.info.get("request_id"),
        client_ip=client_ip or db.info.get("client_ip"),
        before_data=before_data,
        after_data=after_data,
        detail=detail,
        result=result,
    )
    db.add(event)
    return event
