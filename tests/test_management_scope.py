from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import User
from app.services import departments as department_service
from app.services.management_scope import resolve_management_scope
from tests.conftest import login


def _create_department(client: TestClient, csrf: str, name: str, leader_id: str) -> dict:
    response = client.post(
        "/api/v1/departments",
        headers={"X-CSRF-Token": csrf},
        json={"name": name, "leader_id": leader_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_leader_sees_department_members_outside_reporting_line(api: dict) -> None:
    client: TestClient = api["client"]
    admin_csrf = login(client, "admin")
    dept = _create_department(client, admin_csrf, "交付一部", api["users"]["leader"])
    with api["app"].state.session_factory.begin() as db:
        member = db.get(User, api["users"]["member"])
        member.primary_department_id = dept["id"]
        member.leader_id = api["users"]["admin"]
        member2 = db.get(User, api["users"]["member2"])
        member2.primary_department_id = dept["id"]

    login(client, "leader")
    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    member_ids = {item["id"] for item in payload["members"]}
    assert api["users"]["member"] in member_ids
    assert api["users"]["member2"] in member_ids
    assert api["users"]["leader"] not in member_ids
    scope = payload.get("management_scope")
    assert scope is not None
    assert any(
        option["scope_type"] == "department" and option["department_id"] == dept["id"]
        for option in scope["options"]
    )


def test_resolve_management_scope_buckets_and_dedupe(api: dict) -> None:
    client: TestClient = api["client"]
    admin_csrf = login(client, "admin")
    dept = _create_department(client, admin_csrf, "方案二部", api["users"]["leader"])
    with api["app"].state.session_factory.begin() as db:
        member2 = db.get(User, api["users"]["member2"])
        member2.primary_department_id = dept["id"]
        db.flush()
        leader = db.get(User, api["users"]["leader"])
        resolved = resolve_management_scope(db, leader)
        ids = {user.id for user in resolved.members}
        assert api["users"]["member2"] in ids
        assert api["users"]["leader"] not in ids
        assert resolved.scope_type in {"all_led", "department"}
        department_ids = department_service.led_active_department_ids(
            db, api["users"]["leader"]
        )
        assert dept["id"] in department_ids
