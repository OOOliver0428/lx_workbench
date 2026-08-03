from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import ProjectProgress, TaskRelation
from tests.conftest import login


def create_project(
    client: TestClient,
    csrf: str,
    name: str,
    *,
    tag_ids: list[str] | None = None,
    parent_project_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name,
            "tag_ids": tag_ids or [],
            "parent_project_id": parent_project_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def transition_project(
    client: TestClient,
    csrf: str,
    project: dict,
    status: str,
    reason: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/projects/{project['id']}/transition",
        headers={"X-CSRF-Token": csrf},
        json={"revision": project["revision"], "status": status, "reason": reason},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_project_tags_are_independent_from_hierarchy(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    parent = create_project(
        client,
        csrf,
        "客户协同主项目",
        tag_ids=[api["tags"]["opportunity"]],
    )
    child = create_project(
        client,
        csrf,
        "一期需求改造",
        tag_ids=[api["tags"]["change"]],
        parent_project_id=parent["id"],
    )

    assert parent["tags"][0]["name"] == "商机"
    assert child["parent_project_id"] == parent["id"]
    assert child["tags"][0]["name"] == "改造"

    filtered = client.get(
        "/api/v1/projects",
        params={"tag_id": api["tags"]["change"]},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [child["id"]]


def test_duplicate_name_alias_and_hierarchy_cycle_are_rejected(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    parent = create_project(client, csrf, "华东政务协同")

    duplicate = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": " 华东-政务协同 "},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "PROJECT_NAME_CONFLICT"

    alias = client.post(
        f"/api/v1/projects/{parent['id']}/aliases",
        headers={"X-CSRF-Token": csrf},
        json={"revision": parent["revision"], "value": "华东项目"},
    )
    assert alias.status_code == 201, alias.text
    parent = client.get(f"/api/v1/projects/{parent['id']}").json()
    child = create_project(client, csrf, "需求验证子项目", parent_project_id=parent["id"])

    cycle = client.patch(
        f"/api/v1/projects/{parent['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": parent["revision"], "parent_project_id": child["id"]},
    )
    assert cycle.status_code == 400
    assert cycle.json()["code"] == "PROJECT_HIERARCHY_CYCLE"

    alias_conflict = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "华东项目"},
    )
    assert alias_conflict.status_code == 409
    assert alias_conflict.json()["code"] == "PROJECT_ALIAS_CONFLICT"


def test_project_creation_rejects_reversed_date_range(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    response = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "日期校验项目",
            "planned_start_date": "2026-08-10",
            "planned_end_date": "2026-08-01",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PROJECT_DATES"


def test_revision_conflict_prevents_lost_update(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    project = create_project(client, csrf, "并发控制项目")
    first = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": project["revision"], "description": "第一次修改"},
    )
    assert first.status_code == 200

    stale = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"revision": project["revision"], "description": "陈旧修改"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "PROJECT_REVISION_CONFLICT"


def test_project_owner_can_add_and_remove_members(api: dict) -> None:
    client: TestClient = api["client"]
    owner_csrf = login(client, "member")
    project = create_project(client, owner_csrf, "成员流转项目")
    assert project["owner_avatar_key"] == "flat-01"
    owner = next(
        member for member in project["members"] if member["user_id"] == api["users"]["member"]
    )
    assert owner["avatar_key"] == "flat-01"

    added = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers={"X-CSRF-Token": owner_csrf},
        json={"revision": project["revision"], "user_id": api["users"]["member2"]},
    )
    assert added.status_code == 204, added.text
    project = client.get(f"/api/v1/projects/{project['id']}").json()
    added_member = next(
        member for member in project["members"] if member["user_id"] == api["users"]["member2"]
    )
    assert added_member["avatar_key"] == "flat-02"

    member_csrf = login(client, "member2")
    forbidden = client.delete(
        f"/api/v1/projects/{project['id']}/members/{api['users']['member2']}",
        headers={"X-CSRF-Token": member_csrf},
        params={"revision": project["revision"]},
    )
    assert forbidden.status_code == 403

    owner_csrf = login(client, "member")
    removed = client.delete(
        f"/api/v1/projects/{project['id']}/members/{api['users']['member2']}",
        headers={"X-CSRF-Token": owner_csrf},
        params={"revision": project["revision"]},
    )
    assert removed.status_code == 204, removed.text

    project = client.get(f"/api/v1/projects/{project['id']}").json()
    removed_member = next(
        member for member in project["members"] if member["user_id"] == api["users"]["member2"]
    )
    assert removed_member["left_at"] is not None

    owner_removal = client.delete(
        f"/api/v1/projects/{project['id']}/members/{api['users']['member']}",
        headers={"X-CSRF-Token": owner_csrf},
        params={"revision": project["revision"]},
    )
    assert owner_removal.status_code == 400
    assert owner_removal.json()["code"] == "PROJECT_OWNER_REMOVAL_FORBIDDEN"


def test_project_merge_moves_linked_entities_atomically(api: dict) -> None:
    client: TestClient = api["client"]
    member_csrf = login(client, "member")
    source = create_project(
        client,
        member_csrf,
        "重复项目旧名称",
        tag_ids=[api["tags"]["opportunity"]],
    )
    target = create_project(
        client,
        member_csrf,
        "统一项目名称",
        tag_ids=[api["tags"]["change"]],
    )
    source = transition_project(client, member_csrf, source, "active")
    target = transition_project(client, member_csrf, target, "active")

    task_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "project_id": source["id"],
            "title": "完成方案",
            "owner_id": api["users"]["member"],
        },
    )
    assert task_response.status_code == 201, task_response.text
    task = task_response.json()
    target_task_response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "project_id": target["id"],
            "title": "目标项目关联任务",
            "owner_id": api["users"]["member"],
        },
    )
    assert target_task_response.status_code == 201, target_task_response.text
    target_task = target_task_response.json()
    relation_response = client.post(
        "/api/v1/tasks/relations",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "source_task_id": task["id"],
            "target_task_id": target_task["id"],
            "label": "合并后应失效的跨项目关系",
        },
    )
    assert relation_response.status_code == 201, relation_response.text
    relation = relation_response.json()
    progress_response = client.post(
        f"/api/v1/projects/{source['id']}/progress",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "week_start": "2026-07-27",
            "business_stage": "requirement",
            "attention_status": "steady",
            "progress_percent": 30,
            "summary": "合并前的项目进展",
        },
    )
    assert progress_response.status_code == 201, progress_response.text
    progress = progress_response.json()

    record_response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "work_date": "2026-07-27",
            "content": "完成方案评审",
            "minutes": 180,
            "task_id": task["id"],
            "deliverables": [{"name": "总体方案", "url": "https://intranet.example/plan"}],
        },
    )
    assert record_response.status_code == 201, record_response.text
    record = record_response.json()

    leader_csrf = login(client, "leader")
    preview = client.get(
        f"/api/v1/projects/{source['id']}/merge-preview",
        params={"target_project_id": target["id"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["task_count"] == 1
    assert preview.json()["work_record_count"] == 1
    assert preview.json()["deliverable_count"] == 1
    assert preview.json()["progress_count"] == 1
    assert preview.json()["invalidated_task_relation_count"] == 1

    merged = client.post(
        f"/api/v1/projects/{source['id']}/merge",
        headers={"X-CSRF-Token": leader_csrf},
        json={
            "source_revision": source["revision"],
            "target_project_id": target["id"],
            "target_revision": target["revision"],
            "reason": "确认为同一项目",
        },
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["merge_id"]

    moved_task = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert client.get(f"/api/v1/work-records/{record['id']}").status_code == 403

    login(client, "member")
    moved_record = client.get(f"/api/v1/work-records/{record['id']}").json()
    merged_source = client.get(f"/api/v1/projects/{source['id']}").json()
    merged_target = client.get(f"/api/v1/projects/{target['id']}").json()
    assert moved_task["project_id"] == target["id"]
    assert moved_task["revision"] == task["revision"] + 1
    assert moved_record["project_id"] == target["id"]
    assert moved_record["revision"] == record["revision"] + 1
    assert moved_record["deliverables"][0]["project_id"] == target["id"]
    assert merged.json()["moved_counts"]["progress_count"] == 1
    assert merged.json()["moved_counts"]["invalidated_task_relation_count"] == 1
    assert merged_source["status"] == "merged"
    assert merged_source["merged_into_project_id"] == target["id"]
    with api["app"].state.session_factory() as db:
        moved_progress = db.get(ProjectProgress, progress["id"])
        retired_relation = db.get(TaskRelation, relation["id"])
        assert moved_progress
        assert moved_progress.project_id == target["id"]
        assert moved_progress.revision == progress["revision"] + 1
        assert retired_relation
        assert retired_relation.deleted_at is not None
        assert retired_relation.deleted_by == api["users"]["leader"]
    assert {tag["name"] for tag in merged_target["tags"]} == {"商机", "改造"}
    assert "重复项目旧名称" in {alias["value"] for alias in merged_target["aliases"]}
