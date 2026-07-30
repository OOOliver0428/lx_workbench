from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.models import User, WeeklyReport, utc_now
from app.schemas import AIChatOut
from app.services import dashboard as dashboard_service
from tests.conftest import login


def _create_project(client: TestClient, csrf: str, name: str) -> dict:
    response = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task(
    client: TestClient,
    csrf: str,
    *,
    project_id: str,
    owner_id: str,
    title: str,
) -> dict:
    response = client.post(
        "/api/v1/tasks",
        headers={"X-CSRF-Token": csrf},
        json={
            "project_id": project_id,
            "title": title,
            "owner_id": owner_id,
            "priority": "p0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_dashboard_aggregates_real_project_work_and_progress(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    week_start = dashboard_service.normalize_week_start()
    project = _create_project(client, csrf, "航天移动平台替代")
    task = _create_task(
        client,
        csrf,
        project_id=project["id"],
        owner_id=api["users"]["member"],
        title="OIDC 认证联调",
    )

    progress_response = client.post(
        f"/api/v1/projects/{project['id']}/progress",
        headers={"X-CSRF-Token": csrf},
        json={
            "week_start": week_start.isoformat(),
            "business_stage": "solution_confirm",
            "attention_status": "focus",
            "progress_percent": 62,
            "summary": "完成信创终端适配方案确认，启动认证联调",
            "output_summary": "适配确认单",
        },
    )
    assert progress_response.status_code == 201, progress_response.text

    work_response = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": week_start.isoformat(),
            "content": "完成 OIDC 认证接口联调",
            "minutes": 180,
            "project_id": project["id"],
            "task_id": task["id"],
            "deliverables": [
                {
                    "name": "OIDC 联调记录",
                    "url": "https://example.com/oidc",
                }
            ],
        },
    )
    assert work_response.status_code == 201, work_response.text

    dashboard = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["accessible_pages"] == ["opp", "work"]
    assert payload["metrics"]["tracking_count"] == 1
    assert payload["metrics"]["focus_count"] == 1
    assert payload["metrics"]["deliverable_count"] == 1
    assert payload["metrics"]["total_minutes"] == 180
    row = payload["projects"][0]
    assert row["can_manage"] is True
    assert row["business_stage"] == "solution_confirm"
    assert row["progress_percent"] == 62
    assert row["weekly_minutes"] == 180
    assert row["work_summary"].startswith("完成信创终端适配")
    assert row["tasks"][0]["title"] == "OIDC 认证联调"
    assert row["work_items"][0]["content"] == "完成 OIDC 认证接口联调"
    assert payload["deliverables"][0]["name"] == "OIDC 联调记录"


def test_dashboard_never_exposes_other_users_work_records(api: dict) -> None:
    client: TestClient = api["client"]
    week_start = dashboard_service.normalize_week_start()
    member_csrf = login(client, "member")
    project = _create_project(client, member_csrf, "个人记录可见性验证")
    record = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "work_date": week_start.isoformat(),
            "content": "仅记录人和超级管理员可见的工作事实",
            "minutes": 120,
            "project_id": project["id"],
        },
    )
    assert record.status_code == 201, record.text

    with api["app"].state.session_factory.begin() as db:
        member = db.get(User, api["users"]["member"])
        assert member
        member.leader_id = api["users"]["leader"]
        db.add(
            WeeklyReport(
                author_id=member.id,
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
                content="本人已提交周报",
                submitted_content="本人已提交周报",
                submitted_to_id=api["users"]["leader"],
                submitted_at=utc_now(),
                submission_version=1,
            )
        )

    login(client, "leader")
    leader_dashboard = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert leader_dashboard.status_code == 200, leader_dashboard.text
    leader_project = next(
        item
        for item in leader_dashboard.json()["projects"]
        if item["id"] == project["id"]
    )
    assert leader_project["weekly_minutes"] == 0
    assert leader_project["work_items"] == []
    assert "仅记录人和超级管理员可见" not in leader_project["work_summary"]

    login(client, "super_admin")
    super_dashboard = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert super_dashboard.status_code == 200, super_dashboard.text
    super_project = next(
        item
        for item in super_dashboard.json()["projects"]
        if item["id"] == project["id"]
    )
    assert super_project["weekly_minutes"] == 120
    assert super_project["work_items"][0]["id"] == record.json()["id"]


def test_project_progress_and_task_relations_enforce_project_permissions(
    api: dict,
) -> None:
    client: TestClient = api["client"]
    member_csrf = login(client, "member")
    project_a = _create_project(client, member_csrf, "统一认证平台建设")
    project_b = _create_project(client, member_csrf, "移动办公安全改造")
    task_a = _create_task(
        client,
        member_csrf,
        project_id=project_a["id"],
        owner_id=api["users"]["member"],
        title="统一认证改造",
    )
    task_b = _create_task(
        client,
        member_csrf,
        project_id=project_b["id"],
        owner_id=api["users"]["member"],
        title="SSO 接入验证",
    )

    relation = client.post(
        "/api/v1/tasks/relations",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "source_task_id": task_a["id"],
            "target_task_id": task_b["id"],
            "label": "认证协议复用",
        },
    )
    assert relation.status_code == 201, relation.text

    duplicate = client.post(
        "/api/v1/tasks/relations",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "source_task_id": task_b["id"],
            "target_task_id": task_a["id"],
            "label": "重复关系",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "TASK_RELATION_EXISTS"

    member2_csrf = login(client, "member2")
    forbidden = client.post(
        f"/api/v1/projects/{project_a['id']}/progress",
        headers={"X-CSRF-Token": member2_csrf},
        json={
            "week_start": dashboard_service.normalize_week_start().isoformat(),
            "business_stage": "requirement",
            "attention_status": "steady",
            "progress_percent": 20,
            "summary": "无权提交的进展",
        },
    )
    assert forbidden.status_code == 403

    login(client, "member2")
    forbidden_dashboard = client.get("/api/v1/dashboard").json()
    assert all(
        project["can_manage"] is False
        for project in forbidden_dashboard["projects"]
    )

    login(client, "member")
    dashboard = client.get("/api/v1/dashboard").json()
    assert all(project["can_manage"] is True for project in dashboard["projects"])
    assert dashboard["task_links"][0]["label"] == "认证协议复用"


def test_team_summary_requires_complete_submission_or_explicit_force(
    api: dict,
    monkeypatch,
) -> None:
    client: TestClient = api["client"]
    week_start = dashboard_service.normalize_week_start()
    week_end = week_start + timedelta(days=6)

    with api["app"].state.session_factory.begin() as db:
        member = db.get(User, api["users"]["member"])
        member2 = db.get(User, api["users"]["member2"])
        assert member and member2
        member.leader_id = api["users"]["leader"]
        member2.leader_id = api["users"]["leader"]
        for user, text in (
            (member, "项目甲完成方案评审。"),
            (member2, "项目乙完成测试验证。"),
        ):
            db.add(
                WeeklyReport(
                    author_id=user.id,
                    week_start=week_start,
                    week_end=week_end,
                    content=text,
                    submitted_content=text,
                    submitted_to_id=api["users"]["leader"],
                    submitted_at=utc_now(),
                    submission_version=1,
                )
            )

    def fake_complete(*_args, **_kwargs) -> AIChatOut:
        return AIChatOut(
            answer="# 解决方案部门周报\n\n两项工作均有明确交付。",
            model="test-model",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        )

    monkeypatch.setattr(dashboard_service.ai_service, "complete", fake_complete)
    leader_csrf = login(client, "leader")
    incomplete = client.post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week_start.isoformat()},
        headers={"X-CSRF-Token": leader_csrf},
        json={"force": False},
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["code"] == "TEAM_WEEKLY_REPORTS_INCOMPLETE"
    assert incomplete.json()["details"]["missing_members"] == ["团队负责人"]

    forced = client.post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week_start.isoformat()},
        headers={"X-CSRF-Token": leader_csrf},
        json={"force": True},
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["forced"] is True
    assert forced.json()["submitted_count"] == 2
    assert forced.json()["expected_count"] == 3
    team_history = client.get("/api/v1/weekly-reports/team-summaries")
    assert team_history.status_code == 200, team_history.text
    assert team_history.json()[0]["id"] == forced.json()["id"]

    dashboard = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert dashboard.status_code == 200
    assert dashboard.json()["latest_team_summary"]["generation_model"] == "test-model"

    login(client, "member")
    member_dashboard = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert member_dashboard.status_code == 200
    assert member_dashboard.json()["latest_team_summary"] is None
    assert client.get("/api/v1/weekly-reports/team-summaries").status_code == 403

    login(client, "admin")
    other_scope_dashboard = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert other_scope_dashboard.status_code == 200
    assert other_scope_dashboard.json()["latest_team_summary"] is None
    assert client.get("/api/v1/weekly-reports/team-summaries").json() == []
