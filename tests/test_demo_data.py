from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.demo_data import DEMO_LOGIN_NAMES, seed_demo_data
from app.models import Opportunity, Project, Task, User, WeeklyReport, WorkRecord
from tests.conftest import login

DEMO_PASSWORD = "Demo-Password-2026!"


def test_demo_data_is_idempotent_and_covers_full_feature_views(api: dict) -> None:
    client: TestClient = api["client"]
    factory = api["app"].state.session_factory

    with factory.begin() as db:
        first = seed_demo_data(db, password=DEMO_PASSWORD)
    with factory.begin() as db:
        second = seed_demo_data(db, password=DEMO_PASSWORD)
        user_count = db.scalar(
            select(func.count(User.id)).where(User.login_name.in_(DEMO_LOGIN_NAMES))
        )
        project_count = db.scalar(
            select(func.count(Project.id)).where(Project.code.like("DEMO-%"))
        )
        opportunity_count = db.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.code.like("DEMO-OPP-%")
            )
        )
        project_ids = select(Project.id).where(Project.code.like("DEMO-%"))
        task_count = db.scalar(
            select(func.count(Task.id)).where(Task.project_id.in_(project_ids))
        )
        demo_user_ids = select(User.id).where(User.login_name.in_(DEMO_LOGIN_NAMES))
        work_record_count = db.scalar(
            select(func.count(WorkRecord.id)).where(
                WorkRecord.author_id.in_(demo_user_ids)
            )
        )
        weekly_report_count = db.scalar(
            select(func.count(WeeklyReport.id)).where(
                WeeklyReport.author_id.in_(demo_user_ids)
            )
        )

    assert first == second
    assert user_count == first["users"] == 8
    assert project_count == first["projects"] == 10
    assert opportunity_count == first["opportunities"] == 8
    assert task_count == first["tasks"] == 14
    assert work_record_count == first["work_records"] == 31
    assert weekly_report_count == first["weekly_reports"] == 24

    login(client, "演示·方案顾问（全功能）", password=DEMO_PASSWORD)
    full_dashboard = client.get("/api/v1/dashboard")
    assert full_dashboard.status_code == 200, full_dashboard.text
    full_payload = full_dashboard.json()
    assert full_payload["accessible_pages"] == ["opp", "overview"]
    assert full_payload["metrics"]["tracking_count"] == 8
    assert any(item["can_convert"] for item in full_payload["opportunities"])
    assert len(full_payload["task_links"]) == 4
    assert len(full_payload["trends"]) == 5
    assert any(item["total_minutes"] > 0 for item in full_payload["trends"])
    own_records = client.get("/api/v1/work-records")
    assert own_records.status_code == 200
    assert all(
        record["author_display_name"] == "演示·方案顾问（全功能）"
        for record in own_records.json()
    )

    login(client, "demo_opportunity", password=DEMO_PASSWORD)
    opportunity_dashboard = client.get("/api/v1/dashboard")
    assert opportunity_dashboard.status_code == 200
    assert opportunity_dashboard.json()["accessible_pages"] == ["opp"]

    login(client, "demo_leader", password=DEMO_PASSWORD)
    leader_dashboard = client.get("/api/v1/dashboard")
    assert leader_dashboard.status_code == 200
    assert leader_dashboard.json()["latest_team_summary"] is not None
    assert leader_dashboard.json()["metrics"]["member_count"] == 5

    login(client, "demo_newcomer", password=DEMO_PASSWORD)
    no_access = client.get("/api/v1/dashboard")
    assert no_access.status_code == 403
    assert no_access.json()["code"] == "PERMISSION_DENIED"

    inactive = client.post(
        "/api/v1/auth/login",
        json={"login_name": "demo_inactive", "password": DEMO_PASSWORD},
    )
    assert inactive.status_code == 401
