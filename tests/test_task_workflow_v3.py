from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.models import (
    Department,
    DepartmentWork,
    DepartmentWorkStatus,
    DepartmentWorkVisibility,
    Task,
    TaskStatus,
    User,
)
from app.schemas import TaskCreate
from tests.conftest import login
from tests.test_projects import create_project, transition_project


def _active_project(client: TestClient, csrf: str, name: str) -> dict:
    return transition_project(client, csrf, create_project(client, csrf, name), "active")


def _create_project_task(
    client: TestClient,
    csrf: str,
    project_id: str,
    title: str,
    *,
    due_date: str | None = None,
    parent_id: str | None = None,
) -> dict:
    payload: dict[str, object] = {
        "project_id": project_id,
        "title": title,
    }
    if due_date is not None:
        payload["due_date"] = due_date
    if parent_id is not None:
        payload = {"parent_id": parent_id, "title": title}
    response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_department_fixtures(api: dict) -> dict[str, str]:
    with api["app"].state.session_factory.begin() as db:
        member = db.get(User, api["users"]["member"])
        member2 = db.get(User, api["users"]["member2"])
        super_admin_id = api["users"]["super_admin"]
        assert member and member2

        department_a = Department(
            name="Solutions",
            normalized_name="solutions",
            is_active=True,
            created_by=super_admin_id,
        )
        department_b = Department(
            name="Operations",
            normalized_name="operations",
            is_active=True,
            created_by=super_admin_id,
        )
        db.add_all([department_a, department_b])
        db.flush()
        member.primary_department_id = department_a.id
        member2.primary_department_id = department_b.id

        private_work = DepartmentWork(
            code="DWK-PRIVATE",
            name="Private department work",
            normalized_name="privatedepartmentwork",
            department_id=department_a.id,
            owner_id=member.id,
            status=DepartmentWorkStatus.IN_PROGRESS.value,
            visibility=DepartmentWorkVisibility.DEPARTMENT_ONLY.value,
            created_by=member.id,
        )
        public_work = DepartmentWork(
            code="DWK-PUBLIC",
            name="Public department work",
            normalized_name="publicdepartmentwork",
            department_id=department_a.id,
            owner_id=member.id,
            status=DepartmentWorkStatus.IN_PROGRESS.value,
            visibility=DepartmentWorkVisibility.PUBLIC.value,
            created_by=member.id,
        )
        db.add_all([private_work, public_work])
        db.flush()
        return {
            "department_a": department_a.id,
            "department_b": department_b.id,
            "private_work": private_work.id,
            "public_work": public_work.id,
        }


def test_task_source_and_three_level_hierarchy_rules(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project = _active_project(client, csrf, "Atlas hierarchy rollout")
    other_project = _active_project(client, csrf, "Zephyr customer migration")

    root = _create_project_task(client, csrf, project["id"], "Root task")
    child = _create_project_task(
        client,
        csrf,
        project["id"],
        "Child task",
        parent_id=root["id"],
    )
    grandchild = _create_project_task(
        client,
        csrf,
        project["id"],
        "Grandchild task",
        parent_id=child["id"],
    )

    assert root["level"] == 0 and root["parent_id"] is None
    assert child["level"] == 1 and child["project_id"] == project["id"]
    assert grandchild["level"] == 2 and grandchild["project_id"] == project["id"]

    fourth_level = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": csrf},
        json={"parent_id": grandchild["id"], "title": "Forbidden fourth level"},
    )
    assert fourth_level.status_code == 400
    assert fourth_level.json()["code"] == "TASK_LEVEL_LIMIT"

    mismatched_source = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": csrf},
        json={
            "project_id": other_project["id"],
            "parent_id": root["id"],
            "title": "Mismatched child",
        },
    )
    assert mismatched_source.status_code == 400
    assert mismatched_source.json()["code"] == "TASK_PARENT_SOURCE_MISMATCH"

    with pytest.raises(ValueError):
        TaskCreate(
            project_id=project["id"],
            department_work_id="not-a-real-source",
            title="Invalid two-source task",
        )


def test_task_time_scopes_default_status_and_multi_source_or(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project = _active_project(client, csrf, "Orion deadline planning")
    other_project = _active_project(client, csrf, "Beacon service renewal")
    shanghai = timezone(timedelta(hours=8))
    today = datetime.now(shanghai).date()
    week_end = today + timedelta(days=6 - today.weekday())

    overdue = _create_project_task(
        client,
        csrf,
        project["id"],
        "Overdue unfinished",
        due_date=(today - timedelta(days=1)).isoformat(),
    )
    today_task = _create_project_task(
        client,
        csrf,
        project["id"],
        "Due today",
        due_date=today.isoformat(),
    )
    this_week = _create_project_task(
        client,
        csrf,
        project["id"],
        "Due this week",
        due_date=week_end.isoformat(),
    )
    no_deadline = _create_project_task(client, csrf, project["id"], "No deadline")
    future = _create_project_task(
        client,
        csrf,
        other_project["id"],
        "Future other source",
        due_date=(week_end + timedelta(days=1)).isoformat(),
    )
    completed = _create_project_task(
        client,
        csrf,
        project["id"],
        "Completed today",
        due_date=today.isoformat(),
    )
    with api["app"].state.session_factory.begin() as db:
        completed_row = db.get(Task, completed["id"])
        assert completed_row
        completed_row.status = TaskStatus.DONE.value
        completed_row.result = "Completed for filter regression"

    default_response = client.get(
        "/api/v1/tasks",
        params={"project_id": project["id"]},
    )
    assert default_response.status_code == 200, default_response.text
    default_ids = [item["id"] for item in default_response.json()]
    assert default_ids[0] == overdue["id"]
    assert {today_task["id"], this_week["id"], no_deadline["id"]}.issubset(default_ids)
    assert completed["id"] not in default_ids
    assert default_ids[-1] == no_deadline["id"]

    today_response = client.get(
        "/api/v1/tasks",
        params={"project_id": project["id"], "time_scope": "today"},
    )
    assert today_response.status_code == 200
    assert {item["id"] for item in today_response.json()} == {
        overdue["id"],
        today_task["id"],
    }

    all_sources = client.get(
        "/api/v1/tasks",
        params=[
            ("project_ids", project["id"]),
            ("project_ids", other_project["id"]),
            ("time_scope", "all"),
        ],
    )
    assert all_sources.status_code == 200, all_sources.text
    all_ids = {item["id"] for item in all_sources.json()}
    assert future["id"] in all_ids
    assert overdue["id"] in all_ids
    assert completed["id"] not in all_ids

    explicit_done = client.get(
        "/api/v1/tasks",
        params={
            "project_id": project["id"],
            "time_scope": "all",
            "status": "done",
        },
    )
    assert explicit_done.status_code == 200
    assert [item["id"] for item in explicit_done.json()] == [completed["id"]]


def test_department_task_visibility_and_public_is_read_only_scope(api: dict) -> None:
    client: TestClient = api["client"]
    sources = _create_department_fixtures(api)
    member_csrf = login(client, "member")

    private_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "department_work_id": sources["private_work"],
            "title": "Private task",
        },
    )
    assert private_response.status_code == 201, private_response.text
    private_task = private_response.json()

    public_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "department_work_id": sources["public_work"],
            "title": "Public task",
        },
    )
    assert public_response.status_code == 201, public_response.text
    public_task = public_response.json()

    public_external_owner = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "department_work_id": sources["public_work"],
            "title": "Public task cannot grant cross-department edit scope",
            "owner_id": api["users"]["member2"],
        },
    )
    assert public_external_owner.status_code == 400
    assert public_external_owner.json()["code"] == "TASK_ASSIGNEE_SOURCE_INVISIBLE"

    invisible_assignee = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "department_work_id": sources["private_work"],
            "title": "Invalid private task assignee",
            "owner_id": api["users"]["member2"],
        },
    )
    assert invisible_assignee.status_code == 400
    assert invisible_assignee.json()["code"] == "TASK_ASSIGNEE_SOURCE_INVISIBLE"

    member2_csrf = login(client, "member2")
    visible_to_other_department = client.get(
        "/api/v1/tasks",
        params={"time_scope": "all"},
    )
    assert visible_to_other_department.status_code == 200
    visible_ids = {item["id"] for item in visible_to_other_department.json()}
    assert public_task["id"] in visible_ids
    assert private_task["id"] not in visible_ids

    hidden_by_id = client.get(f"/api/v1/tasks/{private_task['id']}")
    assert hidden_by_id.status_code == 404

    cannot_create_via_public_visibility = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member2_csrf},
        json={
            "department_work_id": sources["public_work"],
            "title": "Cross-department write attempt",
        },
    )
    assert cannot_create_via_public_visibility.status_code == 403

    admin_csrf = login(client, "admin")
    admin_visible = client.get("/api/v1/tasks", params={"time_scope": "all"})
    assert admin_visible.status_code == 200
    admin_ids = {item["id"] for item in admin_visible.json()}
    assert {private_task["id"], public_task["id"]}.issubset(admin_ids)

    with api["app"].state.session_factory.begin() as db:
        leader = db.get(User, api["users"]["leader"])
        assert leader
        leader.primary_department_id = sources["department_a"]
        for work_id in (sources["private_work"], sources["public_work"]):
            work = db.get(DepartmentWork, work_id)
            assert work
            work.owner_id = leader.id
    member = next(
        user
        for user in client.get("/api/v1/users").json()
        if user["id"] == api["users"]["member"]
    )
    blocked_department_move = client.patch(
        f"/api/v1/users/{member['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "revision": member["revision"],
            "primary_department_id": sources["department_b"],
        },
    )
    assert blocked_department_move.status_code == 409
    assert (
        blocked_department_move.json()["code"]
        == "DEPARTMENT_TASK_OWNER_REASSIGN_REQUIRED"
    )


def test_progress_history_completion_cascade_and_tree_soft_delete(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project = _active_project(client, csrf, "Task progress and tree operations")
    root = _create_project_task(client, csrf, project["id"], "Progress root")
    child = _create_project_task(
        client,
        csrf,
        project["id"],
        "Progress child",
        parent_id=root["id"],
    )

    root_progress = client.patch(
        f"/api/v1/tasks/{root['id']}/progress",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": root["revision"],
            "enabled": True,
            "percent": 55,
            "reason": "Implementation checkpoint",
        },
    )
    assert root_progress.status_code == 200, root_progress.text
    root = root_progress.json()
    assert root["status"] == "in_progress"
    assert root["progress_percent"] == 55

    blocked_response = client.post(
        f"/api/v1/tasks/{root['id']}/transition",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": root["revision"],
            "status": "blocked",
            "blocker_reason": "Waiting for a dependency",
        },
    )
    assert blocked_response.status_code == 200, blocked_response.text
    resumed_response = client.post(
        f"/api/v1/tasks/{root['id']}/transition",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": blocked_response.json()["revision"],
            "status": "in_progress",
        },
    )
    assert resumed_response.status_code == 200, resumed_response.text
    root = resumed_response.json()

    child_progress = client.patch(
        f"/api/v1/tasks/{child['id']}/progress",
        headers={"X-CSRF-Token": csrf},
        json={"revision": child["revision"], "enabled": True, "percent": 20},
    )
    assert child_progress.status_code == 200, child_progress.text
    child = child_progress.json()

    completed = client.post(
        f"/api/v1/tasks/{root['id']}/transition",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": root["revision"],
            "status": "done",
            "result": "Parent and descendants completed",
            "complete_descendants": True,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "done"
    assert completed.json()["progress_percent"] == 100
    completed_child = client.get(f"/api/v1/tasks/{child['id']}")
    assert completed_child.status_code == 200
    assert completed_child.json()["status"] == "done"
    assert completed_child.json()["progress_percent"] == 100
    assert completed_child.json()["result"] == "Parent and descendants completed"

    history = client.get(f"/api/v1/tasks/{root['id']}/progress-history")
    assert history.status_code == 200, history.text
    assert len(history.json()) == 4
    assert {item["to_percent"] for item in history.json()} == {55, 100}
    assert {
        (item["from_status"], item["to_status"])
        for item in history.json()
    } >= {("in_progress", "blocked"), ("blocked", "in_progress")}

    missing_result_task = _create_project_task(
        client,
        csrf,
        project["id"],
        "Progress result requirement",
    )
    missing_result = client.patch(
        f"/api/v1/tasks/{missing_result_task['id']}/progress",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": missing_result_task["revision"],
            "enabled": True,
            "percent": 100,
        },
    )
    assert missing_result.status_code == 400
    assert missing_result.json()["code"] == "TASK_RESULT_REQUIRED"

    delete_root = _create_project_task(client, csrf, project["id"], "Delete tree root")
    delete_child = _create_project_task(
        client,
        csrf,
        project["id"],
        "Delete tree child",
        parent_id=delete_root["id"],
    )
    deleted = client.request(
        "DELETE",
        f"/api/v1/tasks/{delete_root['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": delete_root["revision"], "reason": "Obsolete task tree"},
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/tasks/{delete_root['id']}").status_code == 404
    assert client.get(f"/api/v1/tasks/{delete_child['id']}").status_code == 404
