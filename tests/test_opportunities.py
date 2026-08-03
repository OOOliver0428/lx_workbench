from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.dashboard import normalize_week_start
from tests.conftest import login


def create_opportunity(
    client: TestClient,
    csrf: str,
    name: str,
    *,
    member_ids: list[str] | None = None,
) -> dict:
    response = client.post(
        "/api/v1/opportunities",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name,
            "customer_name": f"{name}客户",
            "description": "独立商机说明",
            "member_ids": member_ids or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def record_progress(
    client: TestClient,
    csrf: str,
    opportunity: dict,
    *,
    stage: str = "solution_exchange",
) -> dict:
    response = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/progress",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": opportunity["revision"],
            "week_start": normalize_week_start().isoformat(),
            "business_stage": stage,
            "attention_status": "focus",
            "progress_percent": 45,
            "summary": "已完成方案交流并确认项目范围",
            "output_summary": "总体方案初稿",
        },
    )
    assert response.status_code == 201, response.text
    return client.get(f"/api/v1/opportunities/{opportunity['id']}").json()


def test_opportunity_is_independent_and_converts_atomically(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    opportunity = create_opportunity(
        client,
        csrf,
        "省级数据治理商机",
        member_ids=[api["users"]["member2"]],
    )

    assert opportunity["business_stage"] == "lead"
    assert opportunity["linked_project_id"] is None
    assert opportunity["can_convert"] is False
    assert {member["id"] for member in opportunity["members"]} == {
        api["users"]["member"],
        api["users"]["member2"],
    }
    assert client.get("/api/v1/projects").json() == []

    opportunity = record_progress(client, csrf, opportunity)
    assert opportunity["can_convert"] is True
    assert opportunity["revision"] == 2

    conversion = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/convert-to-project",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": opportunity["revision"],
            "project": {
                "name": opportunity["name"],
                "description": "客户：省级数据治理商机客户\n独立商机说明",
                "owner_id": opportunity["owner_id"],
                "tag_ids": [api["tags"]["opportunity"]],
            },
        },
    )
    assert conversion.status_code == 201, conversion.text
    result = conversion.json()
    project = result["project"]
    assert result["opportunity_revision"] == 3
    assert project["name"] == opportunity["name"]
    assert {member["user_id"] for member in project["members"]} == {
        api["users"]["member"],
        api["users"]["member2"],
    }

    linked = client.get(f"/api/v1/opportunities/{opportunity['id']}").json()
    assert linked["linked_project_id"] == project["id"]
    assert linked["linked_project_name"] == project["name"]
    assert linked["can_convert"] is False
    assert linked["business_stage"] == "solution_exchange"

    duplicate = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/convert-to-project",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": linked["revision"],
            "project": {"name": "不应创建的第二个项目"},
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "OPPORTUNITY_ALREADY_LINKED"
    assert len(client.get("/api/v1/projects").json()) == 1


def test_conversion_failure_rolls_back_link_and_project(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    existing = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "重复项目名称"},
    )
    assert existing.status_code == 201
    opportunity = record_progress(
        client,
        csrf,
        create_opportunity(client, csrf, "事务回滚商机"),
    )

    failed = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/convert-to-project",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": opportunity["revision"],
            "project": {"name": "重复项目名称"},
        },
    )
    assert failed.status_code == 409
    fresh = client.get(f"/api/v1/opportunities/{opportunity['id']}").json()
    assert fresh["linked_project_id"] is None
    assert fresh["revision"] == opportunity["revision"]
    assert len(client.get("/api/v1/projects").json()) == 1


def test_opportunity_stage_revision_and_owner_rules(api: dict) -> None:
    client: TestClient = api["client"]
    owner_csrf = login(client, "member")
    opportunity = create_opportunity(client, owner_csrf, "权限与并发商机")

    too_early = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/convert-to-project",
        headers={"X-CSRF-Token": owner_csrf},
        json={
            "revision": opportunity["revision"],
            "project": {"name": "过早创建的项目"},
        },
    )
    assert too_early.status_code == 409
    assert too_early.json()["code"] == "OPPORTUNITY_STAGE_NOT_CONVERTIBLE"

    opportunity = record_progress(client, owner_csrf, opportunity)
    stale = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/progress",
        headers={"X-CSRF-Token": owner_csrf},
        json={
            "revision": 1,
            "week_start": normalize_week_start().isoformat(),
            "business_stage": "solution_confirm",
            "attention_status": "steady",
            "progress_percent": 55,
            "summary": "陈旧版本不应覆盖",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "OPPORTUNITY_REVISION_CONFLICT"

    other_csrf = login(client, "member2")
    forbidden = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/progress",
        headers={"X-CSRF-Token": other_csrf},
        json={
            "revision": opportunity["revision"],
            "week_start": normalize_week_start().isoformat(),
            "business_stage": "solution_confirm",
            "attention_status": "steady",
            "progress_percent": 55,
            "summary": "非负责人不应修改",
        },
    )
    assert forbidden.status_code == 403


def test_dashboard_counts_unlinked_opportunities_not_projects(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    create_opportunity(client, csrf, "尚未立项的独立商机")
    project = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "没有商机的交付项目"},
    )
    assert project.status_code == 201

    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["metrics"]["tracking_count"] == 1
    assert [item["name"] for item in payload["opportunities"]] == [
        "尚未立项的独立商机"
    ]
    assert [item["name"] for item in payload["projects"]] == [
        "没有商机的交付项目"
    ]
