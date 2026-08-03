from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import is_super_admin, jsonable_snapshot
from app.errors import AppError, NotFoundError, PermissionDeniedError
from app.models import Deliverable, ProjectStatus, User, WorkRecord, utc_now
from app.schemas import WorkRecordCreate, WorkRecordUpdate
from app.services.projects import assert_revision, get_project
from app.services.tasks import get_task

WORK_RECORD_SNAPSHOT_FIELDS = (
    "id",
    "author_id",
    "work_date",
    "content",
    "minutes",
    "project_id",
    "task_id",
    "risk",
    "next_action",
    "last_edited_by",
    "delegated_edit_reason",
    "revision",
)

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def get_work_record(db: Session, record_id: str) -> WorkRecord:
    record = db.get(WorkRecord, record_id)
    if not record or record.deleted_at:
        raise NotFoundError("WORK_RECORD_NOT_FOUND", "工作记录不存在")
    return record


def _validate_links(
    db: Session,
    *,
    project_id: str | None,
    task_id: str | None,
) -> str | None:
    if task_id:
        task = get_task(db, task_id)
        if project_id and project_id != task.project_id:
            raise AppError("TASK_PROJECT_MISMATCH", "任务与项目不一致")
        project_id = task.project_id
    if project_id:
        project = get_project(db, project_id)
        if project.status in {
            ProjectStatus.REJECTED.value,
            ProjectStatus.MERGED.value,
            ProjectStatus.ARCHIVED.value,
        }:
            raise AppError("PROJECT_NOT_WRITABLE", "当前项目状态不允许新增工作记录")
    return project_id


def _add_deliverables(
    db: Session,
    record: WorkRecord,
    deliverables: list[object],
    actor: User,
) -> None:
    if deliverables and not record.project_id:
        raise AppError("DELIVERABLE_PROJECT_REQUIRED", "产出物必须关联项目")
    for item in deliverables:
        db.add(
            Deliverable(
                project_id=record.project_id,
                work_record_id=record.id,
                task_id=None,
                name=item.name.strip(),
                url=str(item.url),
                created_by=actor.id,
            )
        )


def _active_deliverables_for_record(
    db: Session,
    record_id: str,
) -> list[Deliverable]:
    return list(
        db.scalars(
            select(Deliverable).where(
                Deliverable.work_record_id == record_id,
                Deliverable.deleted_at.is_(None),
            )
        ).all()
    )


def create_work_record(
    db: Session,
    payload: WorkRecordCreate,
    actor: User,
) -> WorkRecord:
    project_id = _validate_links(
        db,
        project_id=payload.project_id,
        task_id=payload.task_id,
    )
    record = WorkRecord(
        author_id=actor.id,
        work_date=payload.work_date,
        content=payload.content.strip(),
        minutes=payload.minutes,
        project_id=project_id,
        task_id=payload.task_id,
        risk=payload.risk,
        next_action=payload.next_action,
        last_edited_by=actor.id,
    )
    db.add(record)
    db.flush()
    _add_deliverables(db, record, payload.deliverables, actor)
    record_audit(
        db,
        actor=actor,
        action="work_record.create",
        entity_type="work_record",
        entity_id=record.id,
        after_data=jsonable_snapshot(record, WORK_RECORD_SNAPSHOT_FIELDS),
        detail={"deliverableCount": len(payload.deliverables)},
    )
    return record


def list_work_records(
    db: Session,
    actor: User,
    *,
    author_id: str | None = None,
    project_id: str | None = None,
    unassigned_only: bool = False,
    current_week_only: bool = False,
) -> list[WorkRecord]:
    query = select(WorkRecord).where(WorkRecord.deleted_at.is_(None))
    if not is_super_admin(actor):
        query = query.where(WorkRecord.author_id == actor.id)
    elif author_id:
        query = query.where(WorkRecord.author_id == author_id)
    if project_id:
        query = query.where(WorkRecord.project_id == project_id)
    if unassigned_only:
        query = query.where(WorkRecord.project_id.is_(None))
    if current_week_only:
        today = datetime.now(SHANGHAI).date()
        week_start = today - timedelta(days=today.weekday())
        query = query.where(
            WorkRecord.work_date >= week_start,
            WorkRecord.work_date <= week_start + timedelta(days=6),
        )
    return list(
        db.scalars(
            query.order_by(WorkRecord.work_date.desc(), WorkRecord.created_at.desc()).limit(1000)
        ).all()
    )


def update_work_record(
    db: Session,
    record: WorkRecord,
    payload: WorkRecordUpdate,
    actor: User,
) -> WorkRecord:
    if record.author_id != actor.id and not is_super_admin(actor):
        raise PermissionDeniedError("只能修改自己的工作记录")
    if record.author_id != actor.id and not payload.delegated_edit_reason:
        raise AppError("DELEGATED_EDIT_REASON_REQUIRED", "代改他人记录必须填写原因")
    assert_revision(record, payload.revision, entity_name="work_record")
    before = jsonable_snapshot(record, WORK_RECORD_SNAPSHOT_FIELDS)
    fields = payload.model_fields_set - {"revision", "delegated_edit_reason"}

    task_id = payload.task_id if "task_id" in fields else record.task_id
    if "project_id" in fields:
        project_id = payload.project_id
    elif "task_id" in fields and task_id:
        project_id = None
    else:
        project_id = record.project_id
    project_id = _validate_links(db, project_id=project_id, task_id=task_id)
    linked_deliverables = _active_deliverables_for_record(db, record.id)
    if linked_deliverables and not project_id:
        raise AppError(
            "DELIVERABLE_PROJECT_REQUIRED",
            "有交付物的工作记录必须关联项目",
        )
    for field in ("work_date", "content", "minutes", "risk", "next_action"):
        if field in fields:
            value = getattr(payload, field)
            if field == "content" and value:
                value = value.strip()
            setattr(record, field, value)
    now = utc_now()
    moved_deliverable_count = 0
    if "project_id" in fields or "task_id" in fields:
        record.project_id = project_id
        record.task_id = task_id
        for deliverable in linked_deliverables:
            if deliverable.project_id == project_id:
                continue
            deliverable.project_id = project_id
            deliverable.revision += 1
            deliverable.updated_at = now
            moved_deliverable_count += 1
    record.last_edited_by = actor.id
    record.delegated_edit_reason = (
        payload.delegated_edit_reason if actor.id != record.author_id else None
    )
    record.revision += 1
    record.updated_at = now
    record_audit(
        db,
        actor=actor,
        action="work_record.update",
        entity_type="work_record",
        entity_id=record.id,
        before_data=before,
        after_data=jsonable_snapshot(record, WORK_RECORD_SNAPSHOT_FIELDS),
        detail={
            "delegatedEditReason": record.delegated_edit_reason,
            "movedDeliverableCount": moved_deliverable_count,
        },
    )
    return record


def delete_work_record(
    db: Session,
    record: WorkRecord,
    *,
    revision: int,
    reason: str | None,
    actor: User,
) -> None:
    if record.author_id != actor.id and not is_super_admin(actor):
        raise PermissionDeniedError("只能删除自己的工作记录")
    if record.author_id != actor.id and not reason:
        raise AppError("DELEGATED_DELETE_REASON_REQUIRED", "代删他人记录必须填写原因")
    assert_revision(record, revision, entity_name="work_record")
    before = jsonable_snapshot(record, WORK_RECORD_SNAPSHOT_FIELDS)
    now = utc_now()
    linked_deliverables = _active_deliverables_for_record(db, record.id)
    for deliverable in linked_deliverables:
        deliverable.deleted_at = now
        deliverable.deleted_by = actor.id
        deliverable.revision += 1
        deliverable.updated_at = now
    record.deleted_at = now
    record.deleted_by = actor.id
    record.revision += 1
    record_audit(
        db,
        actor=actor,
        action="work_record.delete",
        entity_type="work_record",
        entity_id=record.id,
        before_data=before,
        detail={
            "reason": reason,
            "deletedDeliverableCount": len(linked_deliverables),
        },
    )
