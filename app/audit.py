from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditEvent, User, utc_now


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
    login_failure_retention_days: int | None = None,
    login_failure_max_rows: int | None = None,
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
        if login_failure_retention_days is not None:
            audit_db.execute(
                delete(AuditEvent).where(
                    AuditEvent.action == "auth.login",
                    AuditEvent.result == "failure",
                    AuditEvent.created_at
                    < utc_now() - timedelta(days=login_failure_retention_days),
                )
            )
        if login_failure_max_rows is not None:
            overflow_ids = (
                select(AuditEvent.id)
                .where(
                    AuditEvent.action == "auth.login",
                    AuditEvent.result == "failure",
                )
                .order_by(AuditEvent.created_at.desc())
                .offset(login_failure_max_rows)
            )
            audit_db.execute(
                delete(AuditEvent).where(AuditEvent.id.in_(overflow_ids))
            )
