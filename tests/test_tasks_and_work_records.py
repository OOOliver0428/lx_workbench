from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Deliverable, WorkRecord
from app.services import dashboard as dashboard_service
from tests.conftest import login
from tests.test_projects import create_project, transition_project


def test_work_record_current_week_filter(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    shanghai = timezone(timedelta(hours=8))
    today = datetime.now(shanghai).date()
    week_start = today - timedelta(days=today.weekday())

    for work_date, content in (
        (week_start, "本周筛选命中记录"),
        (week_start - timedelta(days=1), "本周筛选排除记录"),
    ):
        response = client.post(
            "/api/v1/work-records",
            headers={"X-CSRF-Token": csrf},
            json={
                "work_date": work_date.isoformat(),
                "content": content,
                "minutes": 30,
            },
        )
        assert response.status_code == 201, response.text

    filtered = client.get("/api/v1/work-records?current_week_only=true")
    assert filtered.status_code == 200, filtered.text
    contents = {record["content"] for record in filtered.json()}
    assert "本周筛选命中记录" in contents
    assert "本周筛选排除记录" not in contents


def test_task_state_rules_and_work_record_project_inference(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project = transition_project(
        client,
        csrf,
        create_project(client, csrf, "任务闭环项目"),
        "active",
    )
    task_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": csrf},
        json={
            "project_id": project["id"],
            "title": "输出技术方案",
            "owner_id": api["users"]["member2"],
            "priority": "p0",
        },
    )
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()

    missing_result = client.post(
        f"/api/v1/tasks/{task['id']}/transition",
        headers={"X-CSRF-Token": csrf},
        json={"revision": task["revision"], "status": "done"},
    )
    assert missing_result.status_code == 400
    assert missing_result.json()["code"] == "INVALID_TASK_TRANSITION"

    started = client.post(
        f"/api/v1/tasks/{task['id']}/transition",
        headers={"X-CSRF-Token": csrf},
        json={"revision": task["revision"], "status": "in_progress"},
    )
    assert started.status_code == 200, started.text
    task = started.json()

    owner_csrf = login(client, "member2")
    completed = client.post(
        f"/api/v1/tasks/{task['id']}/transition",
        headers={"X-CSRF-Token": owner_csrf},
        json={
            "revision": task["revision"],
            "status": "done",
            "result": "已完成技术方案评审",
        },
    )
    assert completed.status_code == 200, completed.text

    record = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": owner_csrf},
        json={
            "work_date": "2026-07-27",
            "content": "完成技术方案评审",
            "minutes": 240,
            "task_id": task["id"],
        },
    )
    assert record.status_code == 201, record.text
    assert record.json()["project_id"] == project["id"]
    assert record.json()["author_avatar_key"] == "flat-02"
    assert record.json()["last_editor_avatar_key"] == "flat-02"


def test_delegated_work_record_edit_requires_reason_and_audit(api: dict) -> None:
    client: TestClient = api["client"]
    member_csrf = login(client, "member")
    created = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "work_date": "2026-07-27",
            "content": "原始事实",
            "minutes": 60,
        },
    ).json()

    leader_csrf = login(client, "leader")
    forbidden = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": created["revision"], "content": "代改内容"},
    )
    assert forbidden.status_code == 403

    super_admin_csrf = login(client, "super_admin")
    without_reason = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": super_admin_csrf},
        json={"revision": created["revision"], "content": "代改内容"},
    )
    assert without_reason.status_code == 400
    assert without_reason.json()["code"] == "DELEGATED_EDIT_REASON_REQUIRED"

    changed = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": super_admin_csrf},
        json={
            "revision": created["revision"],
            "content": "代改内容",
            "delegated_edit_reason": "修正事实描述",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["last_edited_by"] == api["users"]["super_admin"]
    assert changed.json()["author_avatar_key"] == "flat-01"
    assert changed.json()["last_editor_avatar_key"] == "paper-01"

    audit = client.get(
        "/api/v1/audit-events",
        params={"entity_type": "work_record", "entity_id": created["id"]},
    )
    assert audit.status_code == 200
    update_event = next(item for item in audit.json() if item["action"] == "work_record.update")
    assert update_event["before_data"]["content"] == "原始事实"
    assert update_event["after_data"]["content"] == "代改内容"
    assert update_event["detail"]["delegatedEditReason"] == "修正事实描述"


def test_work_record_duration_uses_half_hour_steps(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")

    below_minimum = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-07-27",
            "content": "短时工作",
            "minutes": 15,
        },
    )
    assert below_minimum.status_code == 422

    not_half_hour_step = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-07-27",
            "content": "非半小时档位",
            "minutes": 45,
        },
    )
    assert not_half_hour_step.status_code == 422

    half_hour = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-07-27",
            "content": "半小时工作",
            "minutes": 30,
        },
    )
    assert half_hour.status_code == 201, half_hour.text
    assert half_hour.json()["minutes"] == 30

    one_and_a_half_hours = client.patch(
        f"/api/v1/work-records/{half_hour.json()['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": half_hour.json()["revision"],
            "minutes": 90,
        },
    )
    assert one_and_a_half_hours.status_code == 200, one_and_a_half_hours.text
    assert one_and_a_half_hours.json()["minutes"] == 90


def test_work_record_deliverables_follow_links_and_source_lifecycle(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    week_start = dashboard_service.normalize_week_start()
    source = transition_project(
        client,
        csrf,
        create_project(client, csrf, "Atlas intake project"),
        "active",
    )
    direct_target = transition_project(
        client,
        csrf,
        create_project(client, csrf, "Beacon data migration"),
        "active",
    )
    target = transition_project(
        client,
        csrf,
        create_project(client, csrf, "Cygnus operations launch"),
        "active",
    )
    target_task_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": csrf},
        json={
            "project_id": target["id"],
            "title": "Move through task association",
            "owner_id": api["users"]["member"],
            "priority": "p1",
        },
    )
    assert target_task_response.status_code == 201, target_task_response.text
    target_task = target_task_response.json()

    created_response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": week_start.isoformat(),
            "content": "Deliverable lifecycle regression sentinel",
            "minutes": 60,
            "project_id": source["id"],
            "deliverables": [
                {
                    "name": "Deliverable lifecycle secret sentinel",
                    "url": "https://example.com/deleted-deliverable-sentinel",
                }
            ],
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    deliverable_id = created["deliverables"][0]["id"]

    direct_move_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": created["revision"],
            "project_id": direct_target["id"],
        },
    )
    assert direct_move_response.status_code == 200, direct_move_response.text
    directly_moved = direct_move_response.json()
    assert directly_moved["project_id"] == direct_target["id"]
    assert directly_moved["deliverables"][0]["project_id"] == direct_target["id"]

    moved_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": directly_moved["revision"],
            "task_id": target_task["id"],
        },
    )
    assert moved_response.status_code == 200, moved_response.text
    moved = moved_response.json()
    assert moved["project_id"] == target["id"]
    assert moved["task_id"] == target_task["id"]
    assert moved["deliverables"][0]["project_id"] == target["id"]

    unassign_response = client.patch(
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": moved["revision"],
            "project_id": None,
            "task_id": None,
        },
    )
    assert unassign_response.status_code == 400
    assert unassign_response.json()["code"] == "DELIVERABLE_PROJECT_REQUIRED"

    deleted_response = client.request(
        "DELETE",
        f"/api/v1/work-records/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": moved["revision"]},
    )
    assert deleted_response.status_code == 204, deleted_response.text

    with api["app"].state.session_factory.begin() as db:
        deleted_record = db.get(WorkRecord, created["id"])
        deleted_deliverable = db.get(Deliverable, deliverable_id)
        assert deleted_record and deleted_record.deleted_at is not None
        assert deleted_deliverable and deleted_deliverable.deleted_at is not None
        assert deleted_deliverable.deleted_by == api["users"]["member"]
        assert deleted_deliverable.project_id == target["id"]

        # Defensive regression: even inconsistent legacy data must not re-expose a
        # deliverable whose source work record has been deleted.
        deleted_deliverable.deleted_at = None
        deleted_deliverable.deleted_by = None

    dashboard_response = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert dashboard_response.status_code == 200, dashboard_response.text
    dashboard_payload = dashboard_response.json()
    assert dashboard_payload["metrics"]["deliverable_count"] == 0
    assert "Deliverable lifecycle secret sentinel" not in dashboard_response.text
    assert "deleted-deliverable-sentinel" not in dashboard_response.text

    with api["app"].state.session_factory() as db:
        deliverable = db.scalar(
            select(Deliverable).where(Deliverable.id == deliverable_id)
        )
        assert deliverable and deliverable.work_record_id == created["id"]
