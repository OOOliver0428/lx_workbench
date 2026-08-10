from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domain import normalize_name
from app.models import (
    Deliverable,
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    DepartmentWorkVisibility,
    Project,
    Task,
    User,
    WorkRecord,
    WorkRecordCreationRequest,
)
from tests.conftest import login


def _seed_department_sources(
    api: dict,
    *,
    first_visibility: str = DepartmentWorkVisibility.DEPARTMENT_ONLY.value,
) -> dict[str, str]:
    """Create two primary departments and two work sources in the first one."""

    with api["app"].state.session_factory.begin() as db:
        department_a = Department(
            name="交付一部",
            normalized_name=normalize_name("交付一部"),
            created_by=api["users"]["admin"],
        )
        department_b = Department(
            name="交付二部",
            normalized_name=normalize_name("交付二部"),
            created_by=api["users"]["admin"],
        )
        db.add_all([department_a, department_b])
        db.flush()

        member = db.get(User, api["users"]["member"])
        member2 = db.get(User, api["users"]["member2"])
        assert member and member2
        member.primary_department_id = department_a.id
        member2.primary_department_id = department_b.id

        first_work = DepartmentWork(
            code=f"DWK-{uuid4().hex[:12].upper()}",
            name="客户资料维护",
            normalized_name=normalize_name("客户资料维护"),
            department_id=department_a.id,
            owner_id=member.id,
            status=DepartmentWorkStatus.IN_PROGRESS.value,
            visibility=first_visibility,
            created_by=member.id,
        )
        second_work = DepartmentWork(
            code=f"DWK-{uuid4().hex[:12].upper()}",
            name="内部知识沉淀",
            normalized_name=normalize_name("内部知识沉淀"),
            department_id=department_a.id,
            owner_id=member.id,
            status=DepartmentWorkStatus.IN_PROGRESS.value,
            visibility=DepartmentWorkVisibility.DEPARTMENT_ONLY.value,
            created_by=member.id,
        )
        db.add_all([first_work, second_work])
        db.flush()

        return {
            "department_a": department_a.id,
            "department_b": department_b.id,
            "first_work": first_work.id,
            "second_work": second_work.id,
        }


def test_quick_create_project_task_record_is_atomic_and_idempotent(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    payload = {
        "idempotency_key": "quick-project-task-0001",
        "work_date": "2026-08-10",
        "content": "完成新项目首次需求梳理",
        "minutes": 90,
        "new_project": {
            "name": "快速录入事务项目",
            "description": "由工作记录入口创建",
        },
        "new_task": {
            "title": "梳理首轮需求",
            "priority": "p0",
            "due_date": "2026-08-14",
        },
    }

    created_response = client.post(
        "/api/v1/work-records/quick-create",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["replayed"] is False
    assert created["created_project_id"]
    assert created["created_task_id"]
    assert created["created_department_work_id"] is None
    assert created["work_record"]["project_id"] == created["created_project_id"]
    assert created["work_record"]["task_id"] == created["created_task_id"]
    assert created["work_record"]["department_work_id"] is None

    replay_response = client.post(
        "/api/v1/work-records/quick-create",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert replay_response.status_code == 200, replay_response.text
    replayed = replay_response.json()
    assert replayed["replayed"] is True
    assert replayed["created_project_id"] == created["created_project_id"]
    assert replayed["created_task_id"] == created["created_task_id"]
    assert replayed["work_record"]["id"] == created["work_record"]["id"]

    changed_payload = deepcopy(payload)
    changed_payload["content"] = "相同幂等键下的另一份内容"
    conflict_response = client.post(
        "/api/v1/work-records/quick-create",
        headers={"X-CSRF-Token": csrf},
        json=changed_payload,
    )
    assert conflict_response.status_code == 409, conflict_response.text
    assert conflict_response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

    with api["app"].state.session_factory() as db:
        project = db.get(Project, created["created_project_id"])
        task = db.get(Task, created["created_task_id"])
        record = db.get(WorkRecord, created["work_record"]["id"])
        request = db.scalar(
            select(WorkRecordCreationRequest).where(
                WorkRecordCreationRequest.actor_id == api["users"]["member"],
                WorkRecordCreationRequest.idempotency_key
                == payload["idempotency_key"],
            )
        )
        assert project and task and record and request
        assert task.project_id == project.id
        assert task.department_work_id is None
        assert record.project_id == project.id
        assert record.task_id == task.id
        assert request.work_record_id == record.id
        assert request.created_project_id == project.id
        assert request.created_task_id == task.id
        assert (
            db.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.normalized_name == normalize_name(payload["new_project"]["name"]))
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkRecordCreationRequest)
                .where(
                    WorkRecordCreationRequest.actor_id == api["users"]["member"],
                    WorkRecordCreationRequest.idempotency_key
                    == payload["idempotency_key"],
                )
            )
            == 1
        )


def test_quick_create_rolls_back_project_when_nested_task_fails(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project_name = "失败后不得残留的项目"
    task_title = "负责人无效的嵌套任务"
    record_content = "该记录也不得残留"
    idempotency_key = "quick-rollback-project-0001"

    response = client.post(
        "/api/v1/work-records/quick-create",
        headers={"X-CSRF-Token": csrf},
        json={
            "idempotency_key": idempotency_key,
            "work_date": "2026-08-10",
            "content": record_content,
            "minutes": 30,
            "new_project": {"name": project_name},
            "new_task": {
                "title": task_title,
                "owner_id": "missing-user-id",
            },
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_USER"

    with api["app"].state.session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.normalized_name == normalize_name(project_name))
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count()).select_from(Task).where(Task.title == task_title)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkRecord)
                .where(WorkRecord.content == record_content)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkRecordCreationRequest)
                .where(
                    WorkRecordCreationRequest.actor_id == api["users"]["member"],
                    WorkRecordCreationRequest.idempotency_key == idempotency_key,
                )
            )
            == 0
        )


def test_department_task_backfills_source_and_public_cross_department_is_read_only(
    api: dict,
) -> None:
    sources = _seed_department_sources(
        api,
        first_visibility=DepartmentWorkVisibility.PUBLIC.value,
    )
    client: TestClient = api["client"]
    member_csrf = login(client, "member")
    task_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "department_work_id": sources["first_work"],
            "title": "整理公开维护清单",
        },
    )
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()

    record_response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "work_date": "2026-08-10",
            "content": "按任务完成维护清单整理",
            "minutes": 60,
            "task_id": task["id"],
        },
    )
    assert record_response.status_code == 201, record_response.text
    record = record_response.json()
    assert record["project_id"] is None
    assert record["department_work_id"] == sources["first_work"]
    assert record["department_work_name"] == "客户资料维护"
    assert record["source_type"] == "department_work"
    assert record["source_id"] == sources["first_work"]
    assert record["task_id"] == task["id"]

    member2_csrf = login(client, "member2")
    readable_work = client.get(
        f"/api/v1/department-works/{sources['first_work']}"
    )
    assert readable_work.status_code == 200, readable_work.text
    readable_task = client.get(f"/api/v1/tasks/{task['id']}")
    assert readable_task.status_code == 200, readable_task.text

    direct_write = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": member2_csrf},
        json={
            "work_date": "2026-08-10",
            "content": "跨部门直接写入应被拒绝",
            "minutes": 30,
            "department_work_id": sources["first_work"],
        },
    )
    assert direct_write.status_code == 403, direct_write.text
    assert direct_write.json()["code"] == "PERMISSION_DENIED"

    task_write = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": member2_csrf},
        json={
            "work_date": "2026-08-10",
            "content": "跨部门通过任务写入也应被拒绝",
            "minutes": 30,
            "task_id": task["id"],
        },
    )
    assert task_write.status_code == 403, task_write.text
    assert task_write.json()["code"] == "PERMISSION_DENIED"


def test_department_deliverable_follows_record_when_moved_by_task(api: dict) -> None:
    sources = _seed_department_sources(api)
    client: TestClient = api["client"]
    csrf = login(client, "member")

    target_task_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": csrf},
        json={
            "department_work_id": sources["second_work"],
            "title": "迁移后的知识沉淀任务",
        },
    )
    assert target_task_response.status_code == 201, target_task_response.text
    target_task = target_task_response.json()

    created_response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-08-10",
            "content": "部门工作交付物来源迁移",
            "minutes": 60,
            "department_work_id": sources["first_work"],
            "deliverables": [
                {
                    "name": "维护清单",
                    "url": "https://example.com/maintenance-list",
                }
            ],
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["project_id"] is None
    assert created["department_work_id"] == sources["first_work"]
    assert len(created["deliverables"]) == 1
    assert created["deliverables"][0]["project_id"] is None
    assert (
        created["deliverables"][0]["department_work_id"]
        == sources["first_work"]
    )

    moved_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": created["revision"],
            "task_id": target_task["id"],
        },
    )
    assert moved_response.status_code == 200, moved_response.text
    moved = moved_response.json()
    assert moved["project_id"] is None
    assert moved["department_work_id"] == sources["second_work"]
    assert moved["task_id"] == target_task["id"]
    assert moved["deliverables"][0]["project_id"] is None
    assert (
        moved["deliverables"][0]["department_work_id"]
        == sources["second_work"]
    )

    with api["app"].state.session_factory() as db:
        deliverable = db.get(Deliverable, moved["deliverables"][0]["id"])
        record = db.get(WorkRecord, moved["id"])
        assert deliverable and record
        assert deliverable.work_record_id == record.id
        assert deliverable.project_id is None
        assert deliverable.department_work_id == sources["second_work"]
        assert record.project_id is None
        assert record.department_work_id == sources["second_work"]
        assert record.task_id == target_task["id"]
