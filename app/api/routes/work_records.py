from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.domain import is_super_admin
from app.errors import PermissionDeniedError
from app.models import PermissionKey, User
from app.schemas import RevisionAction, WorkRecordCreate, WorkRecordOut, WorkRecordUpdate
from app.serializers import work_record_out
from app.services import permissions as permission_service
from app.services import work_records as record_service

router = APIRouter(prefix="/work-records", tags=["work-records"])


@router.get("", response_model=list[WorkRecordOut])
def list_work_records(
    author_id: str | None = None,
    project_id: str | None = None,
    unassigned_only: bool = False,
    current_week_only: bool = False,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> list[WorkRecordOut]:
    permission_service.assert_permission(db, actor, PermissionKey.WORK_RECORDS_VIEW)
    rows = record_service.list_work_records(
        db,
        actor,
        author_id=author_id,
        project_id=project_id,
        unassigned_only=unassigned_only,
        current_week_only=current_week_only,
    )
    return [work_record_out(db, row) for row in rows]


@router.post("", response_model=WorkRecordOut, status_code=201)
def create_work_record(
    payload: WorkRecordCreate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> WorkRecordOut:
    permission_service.assert_permission(db, actor, PermissionKey.WORK_RECORDS_MANAGE)
    return work_record_out(db, record_service.create_work_record(db, payload, actor))


@router.get("/{record_id}", response_model=WorkRecordOut)
def get_work_record(
    record_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db, scope="function"),
) -> WorkRecordOut:
    permission_service.assert_permission(db, actor, PermissionKey.WORK_RECORDS_VIEW)
    record = record_service.get_work_record(db, record_id)
    if record.author_id != actor.id and not is_super_admin(actor):
        raise PermissionDeniedError("无权查看他人的原始工作记录")
    return work_record_out(db, record)


@router.patch("/{record_id}", response_model=WorkRecordOut)
def update_work_record(
    record_id: str,
    payload: WorkRecordUpdate,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> WorkRecordOut:
    permission_service.assert_permission(db, actor, PermissionKey.WORK_RECORDS_MANAGE)
    record = record_service.get_work_record(db, record_id)
    return work_record_out(db, record_service.update_work_record(db, record, payload, actor))


@router.delete("/{record_id}", status_code=204)
def delete_work_record(
    record_id: str,
    payload: RevisionAction,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db, scope="function"),
) -> None:
    permission_service.assert_permission(db, actor, PermissionKey.WORK_RECORDS_MANAGE)
    record_service.delete_work_record(
        db,
        record_service.get_work_record(db, record_id),
        revision=payload.revision,
        reason=payload.reason,
        actor=actor,
    )
