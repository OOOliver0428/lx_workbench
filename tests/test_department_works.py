from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import AuditEvent, PermissionKey, User, UserPermission
from tests.conftest import login

DEPARTMENT_MEMBER_PERMISSIONS = (
    PermissionKey.DEPARTMENTS_VIEW,
    PermissionKey.DEPARTMENT_WORKS_VIEW,
    PermissionKey.DEPARTMENT_WORKS_EDIT,
    PermissionKey.DEPARTMENT_WORKS_CREATE,
)


def _grant_department_permissions(api: dict, *user_keys: str) -> None:
    with api["app"].state.session_factory.begin() as db:
        for user_key in user_keys:
            user_id = api["users"][user_key]
            existing = set(
                db.scalars(
                    select(UserPermission.permission_key).where(UserPermission.user_id == user_id)
                ).all()
            )
            for permission in DEPARTMENT_MEMBER_PERMISSIONS:
                if permission.value not in existing:
                    db.add(
                        UserPermission(
                            user_id=user_id,
                            permission_key=permission.value,
                            granted_by=api["users"]["super_admin"],
                        )
                    )


def _create_department(
    client: TestClient,
    csrf: str,
    name: str,
    *,
    leader_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/departments",
        headers={"X-CSRF-Token": csrf},
        json={"name": name, "leader_id": leader_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_work(
    client: TestClient,
    csrf: str,
    name: str,
    *,
    visibility: str = "department_only",
    department_id: str | None = None,
    owner_id: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "description": "用于验证部门工作权限和生命周期",
        "visibility": visibility,
    }
    if department_id:
        payload["department_id"] = department_id
    if owner_id:
        payload["owner_id"] = owner_id
    response = client.post(
        "/api/v1/department-works",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_department_creation_assigns_initial_leader_and_rejects_duplicates(api: dict) -> None:
    client: TestClient = api["client"]
    admin_csrf = login(client, "admin")
    department = _create_department(
        client,
        admin_csrf,
        "解决方案部",
        leader_id=api["users"]["leader"],
    )

    assert department["leader_id"] == api["users"]["leader"]
    with api["app"].state.session_factory() as db:
        leader = db.get(User, api["users"]["leader"])
        assert leader
        assert leader.primary_department_id == department["id"]

    duplicate = client.post(
        "/api/v1/departments",
        headers={"X-CSRF-Token": admin_csrf},
        json={"name": " 解 决方案部 "},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "DEPARTMENT_NAME_CONFLICT"

    deactivation_blocked = client.patch(
        f"/api/v1/departments/{department['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"revision": department["revision"], "is_active": False},
    )
    assert deactivation_blocked.status_code == 409
    assert deactivation_blocked.json()["code"] == "DEPARTMENT_DEACTIVATION_BLOCKED"

    _grant_department_permissions(api, "member")
    member_csrf = login(client, "member")
    forbidden = client.post(
        "/api/v1/departments",
        headers={"X-CSRF-Token": member_csrf},
        json={"name": "越权创建的部门"},
    )
    assert forbidden.status_code == 403


def test_department_work_visibility_and_edit_scope_are_independent(api: dict) -> None:
    client: TestClient = api["client"]
    admin_csrf = login(client, "admin")
    first = _create_department(
        client,
        admin_csrf,
        "交付一部",
        leader_id=api["users"]["leader"],
    )
    _create_department(
        client,
        admin_csrf,
        "交付二部",
        leader_id=api["users"]["member2"],
    )
    _grant_department_permissions(api, "leader", "member2")

    leader_csrf = login(client, "leader")
    private_work = _create_work(client, leader_csrf, "内部招聘复盘")
    public_work = _create_work(
        client,
        leader_csrf,
        "跨部门知识分享",
        visibility="public",
    )
    assert private_work["department_id"] == first["id"]
    assert private_work["department_name"] == "交付一部"
    assert private_work["owner_display_name"] == "团队负责人"

    with api["app"].state.session_factory.begin() as db:
        same_department_member = db.get(User, api["users"]["member"])
        assert same_department_member
        same_department_member.primary_department_id = first["id"]
    _grant_department_permissions(api, "member")
    member_csrf = login(client, "member")
    same_department_edit = client.patch(
        f"/api/v1/department-works/{private_work['id']}",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "revision": private_work["revision"],
            "description": "同部门成员协作维护",
        },
    )
    assert same_department_edit.status_code == 200, same_department_edit.text

    member2_csrf = login(client, "member2")
    visible = client.get("/api/v1/department-works")
    assert visible.status_code == 200, visible.text
    visible_ids = {item["id"] for item in visible.json()}
    assert public_work["id"] in visible_ids
    assert private_work["id"] not in visible_ids

    private_detail = client.get(f"/api/v1/department-works/{private_work['id']}")
    assert private_detail.status_code == 403
    public_detail = client.get(f"/api/v1/department-works/{public_work['id']}")
    assert public_detail.status_code == 200

    public_edit = client.patch(
        f"/api/v1/department-works/{public_work['id']}",
        headers={"X-CSRF-Token": member2_csrf},
        json={"revision": public_work["revision"], "description": "越权修改"},
    )
    assert public_edit.status_code == 403

    login(client, "admin")
    cross_department = client.get("/api/v1/department-works")
    assert cross_department.status_code == 200
    assert {private_work["id"], public_work["id"]} <= {
        item["id"] for item in cross_department.json()
    }


def test_department_work_lifecycle_revision_and_soft_delete(api: dict) -> None:
    client: TestClient = api["client"]
    admin_csrf = login(client, "admin")
    _create_department(
        client,
        admin_csrf,
        "运营部",
        leader_id=api["users"]["leader"],
    )
    _grant_department_permissions(api, "leader")
    leader_csrf = login(client, "leader")

    work = _create_work(client, leader_csrf, "季度采购")
    active_task_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": leader_csrf},
        json={
            "department_work_id": work["id"],
            "title": "归档前必须处理的任务",
        },
    )
    assert active_task_response.status_code == 201, active_task_response.text
    active_task = active_task_response.json()
    archive_with_active_task = client.post(
        f"/api/v1/department-works/{work['id']}/transition",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": work["revision"], "status": "archived"},
    )
    assert archive_with_active_task.status_code == 409
    assert archive_with_active_task.json()["code"] == "DEPARTMENT_WORK_ACTIVE_TASKS"
    cancelled_task = client.post(
        f"/api/v1/tasks/{active_task['id']}/transition",
        headers={"X-CSRF-Token": leader_csrf},
        json={
            "revision": active_task["revision"],
            "status": "cancelled",
            "cancel_reason": "归档前终结",
        },
    )
    assert cancelled_task.status_code == 200, cancelled_task.text

    completed_response = client.post(
        f"/api/v1/department-works/{work['id']}/transition",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": work["revision"], "status": "completed"},
    )
    assert completed_response.status_code == 200, completed_response.text
    completed = completed_response.json()

    completed_task = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": leader_csrf},
        json={
            "department_work_id": work["id"],
            "title": "完成后不应创建的任务",
        },
    )
    assert completed_task.status_code == 409
    assert completed_task.json()["code"] == "DEPARTMENT_WORK_COMPLETED"

    stale = client.patch(
        f"/api/v1/department-works/{work['id']}",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": work["revision"], "description": "陈旧修改"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "DEPARTMENT_WORK_REVISION_CONFLICT"

    reopened_response = client.post(
        f"/api/v1/department-works/{work['id']}/transition",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": completed["revision"], "status": "in_progress"},
    )
    assert reopened_response.status_code == 200, reopened_response.text
    reopened = reopened_response.json()
    archived_response = client.post(
        f"/api/v1/department-works/{work['id']}/transition",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": reopened["revision"], "status": "archived"},
    )
    assert archived_response.status_code == 200, archived_response.text
    archived = archived_response.json()

    archived_edit = client.patch(
        f"/api/v1/department-works/{work['id']}",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": archived["revision"], "description": "不应生效"},
    )
    assert archived_edit.status_code == 409
    assert archived_edit.json()["code"] == "DEPARTMENT_WORK_ARCHIVED"

    deletable = _create_work(client, leader_csrf, "临时例会")
    deleted = client.request(
        "DELETE",
        f"/api/v1/department-works/{deletable['id']}",
        headers={"X-CSRF-Token": leader_csrf},
        json={"revision": deletable["revision"], "reason": "误建"},
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/department-works/{deletable['id']}").status_code == 404

    with api["app"].state.session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "department_work.delete",
                AuditEvent.entity_id == deletable["id"],
            )
        )
        assert audit
        assert audit.detail == {"reason": "误建"}
