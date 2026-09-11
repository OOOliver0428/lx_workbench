from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.models import PermissionKey, User, UserPermission, WeeklyReport, utc_now
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


def _create_opportunity(client: TestClient, csrf: str, name: str) -> dict:
    response = client.post(
        "/api/v1/opportunities",
        headers={"X-CSRF-Token": csrf},
        json={"name": name, "customer_name": f"{name}客户"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _record_opportunity_progress(
    client: TestClient,
    csrf: str,
    opportunity: dict,
    week_start,
    *,
    stage: str,
    attention: str,
    percent: int,
    summary: str,
    output: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/progress",
        headers={"X-CSRF-Token": csrf},
        json={
            "revision": opportunity["revision"],
            "week_start": week_start.isoformat(),
            "business_stage": stage,
            "attention_status": attention,
            "progress_percent": percent,
            "summary": summary,
            "output_summary": output,
        },
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


def _set_dashboard_permissions(
    api: dict,
    user_id: str,
    *permissions: PermissionKey,
) -> None:
    with api["app"].state.session_factory.begin() as db:
        db.execute(
            delete(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.permission_key.like("dashboard.%"),
            )
        )
        db.add_all(
            UserPermission(
                user_id=user_id,
                permission_key=permission.value,
                granted_by=api["users"]["super_admin"],
            )
            for permission in permissions
        )


def test_dashboard_aggregates_real_project_work_and_progress(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "leader")
    week_start = dashboard_service.normalize_week_start()
    project = _create_project(client, csrf, "航天移动平台替代")
    opportunity = _create_opportunity(client, csrf, "航天移动平台替代商机")
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
    _record_opportunity_progress(
        client,
        csrf,
        opportunity,
        week_start,
        stage="solution_confirm",
        attention="focus",
        percent=62,
        summary="完成信创终端适配方案确认，启动认证联调",
        output="适配确认单",
    )

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
    assert payload["accessible_pages"] == ["opp", "work", "overview"]
    assert payload["metrics"]["tracking_count"] == 1
    assert payload["metrics"]["focus_count"] == 1
    assert payload["metrics"]["deliverable_count"] == 1
    assert payload["metrics"]["total_minutes"] == 180
    opportunity_row = payload["opportunities"][0]
    assert opportunity_row["business_stage"] == "solution_confirm"
    assert opportunity_row["progress_percent"] == 62
    assert opportunity_row["work_summary"].startswith("完成信创终端适配")
    row = payload["projects"][0]
    assert row["can_manage"] is True
    assert row["business_stage"] == "solution_confirm"
    assert row["progress_percent"] == 62
    assert row["weekly_minutes"] == 180
    assert row["work_summary"].startswith("完成信创终端适配")
    assert row["tasks"][0]["title"] == "OIDC 认证联调"
    assert row["work_items"][0]["content"] == "完成 OIDC 认证接口联调"
    assert payload["deliverables"][0]["name"] == "OIDC 联调记录"


def test_dashboard_payload_is_restricted_to_accessible_views(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member2")
    week_start = dashboard_service.normalize_week_start()
    project_a = _create_project(client, csrf, "Dashboard 权限隔离项目 A")
    opportunity_a = _create_opportunity(
        client,
        csrf,
        "Dashboard 权限隔离商机 A",
    )
    project_b = _create_project(client, csrf, "异构系统安全评审")
    task_a = _create_task(
        client,
        csrf,
        project_id=project_a["id"],
        owner_id=api["users"]["member2"],
        title="权限隔离任务 A",
    )
    task_b = _create_task(
        client,
        csrf,
        project_id=project_b["id"],
        owner_id=api["users"]["member2"],
        title="权限隔离任务 B",
    )
    relation = client.post(
        "/api/v1/tasks/relations",
        headers={"X-CSRF-Token": csrf},
        json={
            "source_task_id": task_a["id"],
            "target_task_id": task_b["id"],
            "label": "仅商机视图可见的关系",
        },
    )
    assert relation.status_code == 201, relation.text
    progress = client.post(
        f"/api/v1/projects/{project_a['id']}/progress",
        headers={"X-CSRF-Token": csrf},
        json={
            "week_start": week_start.isoformat(),
            "business_stage": "solution_exchange",
            "attention_status": "steady",
            "progress_percent": 40,
            "output_summary": "OPPORTUNITY_OUTPUT_SENTINEL",
            "summary": "权限隔离测试进展",
        },
    )
    assert progress.status_code == 201, progress.text
    _record_opportunity_progress(
        client,
        csrf,
        opportunity_a,
        week_start,
        stage="solution_exchange",
        attention="steady",
        percent=40,
        summary="权限隔离测试商机进展",
        output="OPPORTUNITY_OUTPUT_SENTINEL",
    )
    work = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": week_start.isoformat(),
            "content": "仅工作视图可见的工作明细",
            "minutes": 60,
            "project_id": project_a["id"],
            "task_id": task_a["id"],
            "deliverables": [
                {
                    "name": "仅工作视图可见的交付物",
                    "url": "https://example.com/dashboard-permission",
                }
            ],
        },
    )
    assert work.status_code == 201, work.text

    _set_dashboard_permissions(
        api,
        api["users"]["member2"],
        PermissionKey.DASHBOARD_OPPORTUNITY_VIEW,
    )
    opportunity = client.get("/api/v1/dashboard").json()
    opportunity_raw = json.dumps(opportunity, ensure_ascii=False)
    assert opportunity["accessible_pages"] == ["opp"]
    assert opportunity["projects"]
    assert opportunity["projects"][0]["tasks"]
    assert all(not project["work_items"] for project in opportunity["projects"])
    assert all(project["weekly_minutes"] is None for project in opportunity["projects"])
    assert work.json()["content"] not in opportunity_raw
    assert work.json()["deliverables"][0]["name"] not in opportunity_raw
    assert "https://example.com/dashboard-permission" not in opportunity_raw
    assert opportunity["task_links"]
    assert opportunity["stage_distribution"]
    assert opportunity["stage_timeline"]
    assert opportunity["members"] == []
    assert opportunity["deliverables"] == []
    assert opportunity["trends"] == []
    assert opportunity["metrics"]["total_minutes"] == 0
    assert opportunity["metrics"]["deliverable_count"] == 0
    assert opportunity["metrics"]["submitted_count"] == 0
    assert opportunity["metrics"]["member_count"] == 0
    assert opportunity["latest_team_summary"] is None

    _set_dashboard_permissions(
        api,
        api["users"]["leader"],
        PermissionKey.DASHBOARD_WORK_VIEW,
    )
    leader_csrf = login(client, "leader")
    leader_work = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": leader_csrf},
        json={
            "work_date": week_start.isoformat(),
            "content": "负责人本周工作视图记录",
            "minutes": 30,
            "project_id": project_a["id"],
            "task_id": task_a["id"],
            "deliverables": [
                {
                    "name": "负责人可见交付物",
                    "url": "https://example.com/leader-deliverable",
                }
            ],
        },
    )
    assert leader_work.status_code == 201, leader_work.text
    work_view = client.get("/api/v1/dashboard").json()
    work_view_raw = json.dumps(work_view, ensure_ascii=False)
    assert work_view["accessible_pages"] == ["work"]
    assert work_view["members"]
    assert any(
        item["name"] == "负责人可见交付物" for item in work_view["deliverables"]
    )
    assert any(project["work_items"] for project in work_view["projects"])
    assert all(not project["tasks"] for project in work_view["projects"])
    assert all(not project["stage_history"] for project in work_view["projects"])
    assert all(project["can_manage"] is False for project in work_view["projects"])
    assert work_view["task_links"] == []
    assert work_view["trends"] == []
    assert work_view["stage_distribution"] == []
    assert work_view["stage_timeline"] == []
    assert work_view["metrics"]["tracking_count"] == 0
    assert work_view["metrics"]["focus_count"] == 0
    assert work_view["metrics"]["stage_advanced_count"] == 0
    assert work_view["metrics"]["deliverable_count"] >= 1
    assert work_view["metrics"]["coordinate_count"] == 0
    assert work_view["metrics"]["total_minutes"] >= 30
    assert progress.json()["summary"] not in work_view_raw
    assert "OPPORTUNITY_OUTPUT_SENTINEL" not in work_view_raw

    _set_dashboard_permissions(
        api,
        api["users"]["member2"],
        PermissionKey.DASHBOARD_OVERVIEW_VIEW,
    )
    login(client, "member2")
    overview = client.get("/api/v1/dashboard").json()
    assert overview["accessible_pages"] == ["overview"]
    assert overview["projects"] == []
    assert overview["deliverables"] == []
    assert overview["task_links"] == []
    assert overview["members"]
    assert all(member["weekly_minutes"] is None for member in overview["members"])
    assert len(overview["trends"]) == 5
    assert overview["stage_distribution"]
    assert overview["stage_timeline"]
    assert overview["metrics"]["tracking_count"] == 1
    assert overview["metrics"]["total_minutes"] == 0
    assert overview["metrics"]["submitted_count"] == 0
    assert overview["metrics"]["member_count"] == 0
    assert overview["latest_team_summary"] is None


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
    # 管理范围内成员的工作贡献对负责人可见（0.4.0 口径）。
    assert leader_project["weekly_minutes"] == 120
    assert leader_project["work_items"]
    assert "仅记录人和超级管理员可见" in leader_project["work_summary"]

    login(client, "member2")
    member2_dashboard = client.get(
        "/api/v1/dashboard",
        params={"week_start": week_start.isoformat()},
    )
    assert member2_dashboard.status_code == 200, member2_dashboard.text
    member2_project = next(
        item
        for item in member2_dashboard.json()["projects"]
        if item["id"] == project["id"]
    )
    assert not member2_project["weekly_minutes"]
    assert member2_project["work_items"] == []
    assert "仅记录人和超级管理员可见" not in member2_project["work_summary"]

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
    api["app"].state.llm_guard.cooldown_seconds["team_summary"] = 0
    # 负责人本人不计入管理范围；成员与 member2 均已提交时不应再 409。
    incomplete = client.post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week_start.isoformat()},
        headers={"X-CSRF-Token": leader_csrf},
        json={"force": False},
    )
    assert incomplete.status_code == 200, incomplete.text
    assert incomplete.json()["submitted_count"] == 2
    assert incomplete.json()["expected_count"] == 2

    api["app"].state.llm_guard.cooldown_seconds["team_summary"] = 0
    forced = client.post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week_start.isoformat()},
        headers={"X-CSRF-Token": leader_csrf},
        json={"force": True},
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["forced"] is True
    assert forced.json()["submitted_count"] == 2
    assert forced.json()["expected_count"] == 2
    api["app"].state.llm_guard.cooldown_seconds["team_summary"] = 0
    regenerated = client.post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week_start.isoformat()},
        headers={"X-CSRF-Token": leader_csrf},
        json={"force": True},
    )
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["id"] == forced.json()["id"]
    assert regenerated.json()["revision"] == forced.json()["revision"] + 1
    team_history = client.get("/api/v1/weekly-reports/team-summaries")
    assert team_history.status_code == 200, team_history.text
    assert [item["id"] for item in team_history.json()] == [forced.json()["id"]]

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


def test_team_summary_recurses_reports_and_orders_formal_content_by_hierarchy(
    api: dict,
    monkeypatch,
) -> None:
    client: TestClient = api["client"]
    week_start = dashboard_service.normalize_week_start()
    week_end = week_start + timedelta(days=6)
    captured: dict = {}
    report_ids: dict[str, str] = {}

    with api["app"].state.session_factory.begin() as db:
        admin = db.get(User, api["users"]["admin"])
        leader = db.get(User, api["users"]["leader"])
        member = db.get(User, api["users"]["member"])
        member2 = db.get(User, api["users"]["member2"])
        assert admin and leader and member and member2

        member.leader_id = admin.id
        scoped_users = (admin, leader, member, member2)
        submitted_to = {
            admin.id: None,
            leader.id: admin.id,
            member.id: admin.id,
            # The recursive report was submitted to its direct leader, not to
            # the administrator who is generating this organization summary.
            member2.id: leader.id,
        }
        for user in scoped_users:
            report = WeeklyReport(
                author_id=user.id,
                week_start=week_start,
                week_end=week_end,
                content=f"DRAFT-CONTENT-{user.id}",
                submitted_content=f"FORMAL-CONTENT-{user.id}",
                submitted_to_id=submitted_to[user.id],
                submitted_at=utc_now(),
                submission_version=1,
            )
            db.add(report)
            db.flush()
            report_ids[user.id] = report.id

    def fake_complete(
        _db,
        _settings,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AIChatOut:
        captured["messages"] = messages
        captured["max_tokens"] = max_tokens
        return AIChatOut(
            answer="# Recursive organization summary",
            model="test-model",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        )

    monkeypatch.setattr(dashboard_service.ai_service, "complete", fake_complete)
    admin_csrf = login(client, "admin")
    response = client.post(
        "/api/v1/dashboard/team-summary",
        params={"week_start": week_start.isoformat()},
        headers={"X-CSRF-Token": admin_csrf},
        json={"force": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    # 系统管理员本人不计入管理范围汇总（规则：负责人自己的周报单独展示）。
    assert payload["submitted_count"] == 3
    assert payload["expected_count"] == 3
    assert payload["included_leader_count"] == 1

    expected_author_order = [
        api["users"]["leader"],
        api["users"]["member"],
        api["users"]["member2"],
    ]
    assert [item["author_id"] for item in payload["source_reports"]] == (
        expected_author_order
    )
    assert [item["report_id"] for item in payload["source_reports"]] == [
        report_ids[user_id] for user_id in expected_author_order
    ]
    assert [item["order"] for item in payload["source_reports"]] == [1, 2, 3]
    # 汇报树深度：不含 admin 本人；leader/member 为 admin 直属，member2 再下一级。
    assert [item["depth"] for item in payload["source_reports"]] == [1, 1, 2]

    system_context = next(
        message["content"]
        for message in captured["messages"]
        if "以下为已提交个人周报" in message["content"]
    )
    assert "DRAFT-CONTENT-" not in system_context
    formal_positions = [
        system_context.index(f"FORMAL-CONTENT-{user_id}")
        for user_id in expected_author_order
    ]
    assert formal_positions == sorted(formal_positions)
    assert captured["max_tokens"] == 6144
