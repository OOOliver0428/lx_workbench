from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

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


def record_audit_committed(
    session_factory: sessionmaker[Session],
    *,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    request_id: str | None = None,
    client_ip: str | None = None,
    detail: dict[str, Any] | None = None,
    result: str,
) -> None:
    """Persist a security event in a transaction independent of the request."""

    with session_factory.begin() as audit_db:
        audit_db.add(
            AuditEvent(
                actor_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                request_id=request_id,
                client_ip=client_ip,
                detail=detail,
                result=result,
            )
        )
