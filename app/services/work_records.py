from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.domain import is_super_admin, jsonable_snapshot
from app.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import (
    Deliverable,
    DepartmentWorkStatus,
    PermissionKey,
    ProjectStatus,
    User,
    WorkRecord,
    WorkRecordCreationRequest,
    WorkRecordTimeBlock,
    utc_now,
)
from app.schemas import (
    TaskCreate,
    TimeBlockInput,
    WorkRecordCreate,
    WorkRecordQuickCreate,
    WorkRecordUpdate,
)
from app.services import department_works as department_work_service
from app.services import permissions as permission_service
from app.services import projects as project_service
from app.services import tasks as task_service
from app.services.projects import assert_revision, get_project

WORK_RECORD_SNAPSHOT_FIELDS = (
    "id",
    "author_id",
    "work_date",
    "content",
    "minutes",
    "project_id",
    "department_work_id",
    "task_id",
    "risk",
    "next_action",
    "last_edited_by",
    "delegated_edit_reason",
    "revision",
)

SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class QuickCreateResult:
    work_record: WorkRecord
    created_project_id: str | None
    created_department_work_id: str | None
    created_task_id: str | None
    replayed: bool


def _time_blocks_minutes(blocks: list[TimeBlockInput]) -> int:
    return sum(block.end - block.start for block in blocks)


def _replace_time_blocks(
    record: WorkRecord,
    blocks: list[TimeBlockInput],
) -> None:
    record.time_blocks = [
        WorkRecordTimeBlock(
            start_minute=block.start,
            end_minute=block.end,
        )
        for block in sorted(blocks, key=lambda block: (block.start, block.end))
    ]


def _work_record_snapshot(record: WorkRecord) -> dict[str, object]:
    snapshot = jsonable_snapshot(record, WORK_RECORD_SNAPSHOT_FIELDS)
    snapshot["time_blocks"] = [
        {"start": block.start_minute, "end": block.end_minute} for block in record.time_blocks
    ]
    return snapshot


def get_work_record(db: Session, record_id: str) -> WorkRecord:
    record = db.get(WorkRecord, record_id)
    if not record or record.deleted_at:
        raise NotFoundError("WORK_RECORD_NOT_FOUND", "工作记录不存在")
    return record


def _require_department_work_record_scope(
    db: Session,
    *,
    actor: User,
    department_work_id: str,
) -> None:
    permission_service.assert_permission(
        db,
        actor,
        PermissionKey.DEPARTMENT_WORKS_VIEW,
    )
    work = department_work_service.get_department_work(db, department_work_id)
    department_work_service.require_view_department_work(db, actor, work)
    if work.status == DepartmentWorkStatus.ARCHIVED.value:
        raise ConflictError(
            "DEPARTMENT_WORK_ARCHIVED",
            "已归档部门工作不能变更工作记录",
        )
    if actor.primary_department_id != work.department_id and not is_super_admin(actor):
        raise PermissionDeniedError("公开范围仅允许跨部门查看，不能跨部门变更工作记录")


def _validate_links(
    db: Session,
    *,
    actor: User,
    project_id: str | None,
    department_work_id: str | None,
    task_id: str | None,
) -> tuple[str | None, str | None]:
    if project_id and department_work_id:
        raise AppError(
            "WORK_RECORD_SOURCE_INVALID",
            "工作记录不能同时关联项目和部门工作",
        )
    if task_id:
        task = task_service.get_task(db, task_id, actor=actor)
        if project_id and project_id != task.project_id:
            raise AppError("TASK_SOURCE_MISMATCH", "任务与工作来源不一致")
        if department_work_id and department_work_id != task.department_work_id:
            raise AppError("TASK_SOURCE_MISMATCH", "任务与工作来源不一致")
        project_id = task.project_id
        department_work_id = task.department_work_id
    if project_id:
        project = get_project(db, project_id)
        if project.status in {
            ProjectStatus.REJECTED.value,
            ProjectStatus.MERGED.value,
            ProjectStatus.ARCHIVED.value,
        }:
            raise AppError("PROJECT_NOT_WRITABLE", "当前项目状态不允许新增工作记录")
    if department_work_id:
        _require_department_work_record_scope(
            db,
            actor=actor,
            department_work_id=department_work_id,
        )
    return project_id, department_work_id


def _add_deliverables(
    db: Session,
    record: WorkRecord,
    deliverables: list[object],
    actor: User,
) -> None:
    if deliverables and not (record.project_id or record.department_work_id):
        # Keep the historical code so existing API clients do not need a flag day.
        raise AppError("DELIVERABLE_PROJECT_REQUIRED", "产出物必须关联项目或部门工作")
    for item in deliverables:
        db.add(
            Deliverable(
                project_id=record.project_id,
                department_work_id=record.department_work_id,
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
    project_id, department_work_id = _validate_links(
        db,
        actor=actor,
        project_id=payload.project_id,
        department_work_id=payload.department_work_id,
        task_id=payload.task_id,
    )
    record = WorkRecord(
        author_id=actor.id,
        work_date=payload.work_date,
        content=payload.content.strip(),
        minutes=(
            _time_blocks_minutes(payload.time_blocks) if payload.time_blocks else payload.minutes
        ),
        project_id=project_id,
        department_work_id=department_work_id,
        task_id=payload.task_id,
        risk=payload.risk,
        next_action=payload.next_action,
        last_edited_by=actor.id,
    )
    _replace_time_blocks(record, payload.time_blocks)
    db.add(record)
    db.flush()
    _add_deliverables(db, record, payload.deliverables, actor)
    record_audit(
        db,
        actor=actor,
        action="work_record.create",
        entity_type="work_record",
        entity_id=record.id,
        after_data=_work_record_snapshot(record),
        detail={"deliverableCount": len(payload.deliverables)},
    )
    return record


def list_work_records(
    db: Session,
    actor: User,
    *,
    author_id: str | None = None,
    project_id: str | None = None,
    department_work_id: str | None = None,
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
    if department_work_id:
        query = query.where(WorkRecord.department_work_id == department_work_id)
    if unassigned_only:
        query = query.where(
            WorkRecord.project_id.is_(None),
            WorkRecord.department_work_id.is_(None),
        )
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
    before = _work_record_snapshot(record)
    fields = payload.model_fields_set - {
        "revision",
        "delegated_edit_reason",
        "time_blocks",
    }

    task_id = payload.task_id if "task_id" in fields else record.task_id
    project_id = payload.project_id if "project_id" in fields else record.project_id
    department_work_id = (
        payload.department_work_id
        if "department_work_id" in fields
        else record.department_work_id
    )
    if "task_id" in fields and task_id:
        if "project_id" not in fields:
            project_id = None
        if "department_work_id" not in fields:
            department_work_id = None
    project_id, department_work_id = _validate_links(
        db,
        actor=actor,
        project_id=project_id,
        department_work_id=department_work_id,
        task_id=task_id,
    )
    linked_deliverables = _active_deliverables_for_record(db, record.id)
    if linked_deliverables and not (project_id or department_work_id):
        raise AppError(
            "DELIVERABLE_PROJECT_REQUIRED",
            "有交付物的工作记录必须关联项目或部门工作",
        )
    for field in ("work_date", "content", "minutes", "risk", "next_action"):
        if field in fields:
            value = getattr(payload, field)
            if field == "content" and value:
                value = value.strip()
            setattr(record, field, value)
    if "time_blocks" in payload.model_fields_set and payload.time_blocks is not None:
        _replace_time_blocks(record, payload.time_blocks)
        if payload.time_blocks:
            record.minutes = _time_blocks_minutes(payload.time_blocks)
    now = utc_now()
    moved_deliverable_count = 0
    if {"project_id", "department_work_id", "task_id"} & fields:
        record.project_id = project_id
        record.department_work_id = department_work_id
        record.task_id = task_id
        for deliverable in linked_deliverables:
            if (
                deliverable.project_id == project_id
                and deliverable.department_work_id == department_work_id
            ):
                continue
            deliverable.project_id = project_id
            deliverable.department_work_id = department_work_id
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
        after_data=_work_record_snapshot(record),
        detail={
            "delegatedEditReason": record.delegated_edit_reason,
            "movedDeliverableCount": moved_deliverable_count,
        },
    )
    return record


def _quick_payload_hash(payload: WorkRecordQuickCreate) -> str:
    excluded_fields = {"idempotency_key"}
    if "time_blocks" not in payload.model_fields_set:
        # Keep hashes compatible with requests persisted before this optional
        # field existed, so old clients can still replay an existing key.
        excluded_fields.add("time_blocks")
    canonical = payload.model_dump(mode="json", exclude=excluded_fields)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _existing_quick_request(
    db: Session,
    *,
    actor: User,
    idempotency_key: str,
    payload_hash: str,
) -> QuickCreateResult | None:
    request = db.scalar(
        select(WorkRecordCreationRequest).where(
            WorkRecordCreationRequest.actor_id == actor.id,
            WorkRecordCreationRequest.idempotency_key == idempotency_key,
        )
    )
    if request is None:
        return None
    if request.payload_hash != payload_hash:
        raise ConflictError(
            "IDEMPOTENCY_KEY_REUSED",
            "该幂等键已用于另一份请求，请更换后重试",
        )
    record = db.get(WorkRecord, request.work_record_id)
    if record is None or record.deleted_at:
        raise ConflictError(
            "IDEMPOTENT_RESULT_UNAVAILABLE",
            "该请求已处理，但原工作记录当前不可用",
        )
    return QuickCreateResult(
        work_record=record,
        created_project_id=request.created_project_id,
        created_department_work_id=request.created_department_work_id,
        created_task_id=request.created_task_id,
        replayed=True,
    )


def quick_create_work_record(
    db: Session,
    payload: WorkRecordQuickCreate,
    actor: User,
) -> QuickCreateResult:
    """Create optional source/task plus one record in the request transaction."""

    payload_hash = _quick_payload_hash(payload)
    existing = _existing_quick_request(
        db,
        actor=actor,
        idempotency_key=payload.idempotency_key,
        payload_hash=payload_hash,
    )
    if existing is not None:
        return existing

    project_id = payload.project_id
    department_work_id = payload.department_work_id
    task_id = payload.task_id
    created_project_id: str | None = None
    created_department_work_id: str | None = None
    created_task_id: str | None = None

    if payload.new_project is not None:
        permission_service.assert_permission(db, actor, PermissionKey.PROJECTS_CREATE)
        project = project_service.create_project(db, payload.new_project, actor)
        project_id = project.id
        created_project_id = project.id
    elif payload.new_department_work is not None:
        permission_service.assert_permission(
            db,
            actor,
            PermissionKey.DEPARTMENT_WORKS_CREATE,
        )
        department_work = department_work_service.create_department_work(
            db,
            payload.new_department_work,
            actor,
        )
        department_work_id = department_work.id
        created_department_work_id = department_work.id

    if payload.new_task is not None:
        permission_service.assert_permission(db, actor, PermissionKey.TASKS_CREATE)
        task_payload = TaskCreate(
            project_id=project_id,
            department_work_id=department_work_id,
            parent_id=payload.new_task.parent_id,
            title=payload.new_task.title,
            description=payload.new_task.description,
            owner_id=payload.new_task.owner_id,
            collaborator_ids=payload.new_task.collaborator_ids,
            priority=payload.new_task.priority,
            due_date=payload.new_task.due_date,
        )
        task = task_service.create_task(db, task_payload, actor)
        task_id = task.id
        project_id = task.project_id
        department_work_id = task.department_work_id
        created_task_id = task.id

    record_payload = WorkRecordCreate(
        work_date=payload.work_date,
        content=payload.content,
        minutes=payload.minutes,
        project_id=project_id,
        department_work_id=department_work_id,
        task_id=task_id,
        risk=payload.risk,
        next_action=payload.next_action,
        deliverables=payload.deliverables,
        time_blocks=payload.time_blocks,
    )
    record = create_work_record(db, record_payload, actor)
    request = WorkRecordCreationRequest(
        actor_id=actor.id,
        idempotency_key=payload.idempotency_key,
        payload_hash=payload_hash,
        work_record_id=record.id,
        created_project_id=created_project_id,
        created_department_work_id=created_department_work_id,
        created_task_id=created_task_id,
    )
    db.add(request)
    db.flush()
    return QuickCreateResult(
        work_record=record,
        created_project_id=created_project_id,
        created_department_work_id=created_department_work_id,
        created_task_id=created_task_id,
        replayed=False,
    )


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
    if record.department_work_id:
        _require_department_work_record_scope(
            db,
            actor=actor,
            department_work_id=record.department_work_id,
        )
    assert_revision(record, revision, entity_name="work_record")
    before = _work_record_snapshot(record)
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
