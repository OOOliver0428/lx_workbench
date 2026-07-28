from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login


def test_root_redirects_to_api_docs(api: dict) -> None:
    client: TestClient = api["client"]
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_local_frontend_origin_is_allowed(api: dict) -> None:
    client: TestClient = api["client"]
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_initial_password_must_be_changed_before_business_access(api: dict) -> None:
    client: TestClient = api["client"]
    admin_csrf = login(client, "admin")
    created = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "display_name": "新成员",
            "password": "Initial-Password-2026",
            "role": "member",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["must_change_password"] is True
    assert created.json()["login_name"].startswith("u")
    assert len(created.json()["login_name"]) == 9
    new_login_name = created.json()["login_name"]

    client.cookies.clear()
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"login_name": new_login_name, "password": "Initial-Password-2026"},
    )
    assert logged_in.status_code == 200, logged_in.text
    old_session_token = client.cookies.get("mvp_session")
    logged_in_again = client.post(
        "/api/v1/auth/login",
        json={"login_name": new_login_name, "password": "Initial-Password-2026"},
    )
    assert logged_in_again.status_code == 200, logged_in_again.text
    csrf = logged_in_again.json()["csrf_token"]

    blocked = client.get("/api/v1/projects")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["csrf_token"] == csrf
    assert me.json()["user"]["login_name"] == new_login_name

    too_short = client.post(
        "/api/v1/auth/change-password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": "Initial-Password-2026",
            "new_password": "1234",
        },
    )
    assert too_short.status_code == 422

    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": "Initial-Password-2026",
            "new_password": "abcde",
        },
    )
    assert changed.status_code == 204, changed.text
    assert client.get("/api/v1/projects").status_code == 200

    client.cookies.clear()
    client.cookies.set("mvp_session", old_session_token)
    old_session = client.get("/api/v1/auth/me")
    assert old_session.status_code == 401
    assert old_session.json()["code"] == "SESSION_EXPIRED"

    client.cookies.clear()
    relogged = client.post(
        "/api/v1/auth/login",
        json={"login_name": new_login_name, "password": "abcde"},
    )
    assert relogged.status_code == 200, relogged.text


def test_user_creation_only_accepts_name_role_and_initial_password(api: dict) -> None:
    client: TestClient = api["client"]

    member_csrf = login(client, "member")
    forbidden = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "display_name": "无权限创建",
            "password": "Initial-Password-2026",
            "role": "member",
        },
    )
    assert forbidden.status_code == 403

    admin_csrf = login(client, "admin")
    extra_fields = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "display_name": "契约外字段",
            "password": "Initial-Password-2026",
            "role": "member",
            "login_name": "should-not-be-accepted",
            "leader_id": api["users"]["leader"],
        },
    )
    assert extra_fields.status_code == 422

    created = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "display_name": "新建账号",
            "password": "Initial-Password-2026",
            "role": "team_leader",
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["display_name"] == "新建账号"
    assert payload["role"] == "team_leader"
    assert payload["leader_id"] is None
    assert payload["avatar_key"] is None
    assert payload["login_name"].startswith("u")


def test_all_roles_can_choose_only_system_avatars(api: dict) -> None:
    client: TestClient = api["client"]
    for index, login_name in enumerate(
        ("member", "leader", "admin", "super_admin"),
        start=1,
    ):
        csrf = login(client, login_name)
        options = client.get("/api/v1/profile/avatars")
        assert options.status_code == 200, options.text
        assert len(options.json()) == 56
        assert {option["style"] for option in options.json()} == {
            "flat",
            "clay-soft",
            "pixel-soft",
            "paper",
            "line",
            "pixel",
            "clay",
        }

        context = client.get("/api/v1/auth/me").json()
        avatar_key = f"paper-{index:02d}"
        updated = client.patch(
            "/api/v1/profile/avatar",
            headers={"X-CSRF-Token": csrf},
            json={
                "revision": context["user"]["revision"],
                "avatar_key": avatar_key,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["avatar_key"] == avatar_key

        invalid = client.patch(
            "/api/v1/profile/avatar",
            headers={"X-CSRF-Token": csrf},
            json={
                "revision": updated.json()["revision"],
                "avatar_key": "../../outside",
            },
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "AVATAR_NOT_FOUND"


def test_authentication_and_csrf_are_required(api: dict) -> None:
    client: TestClient = api["client"]
    unauthorized = client.get("/api/v1/projects")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["request_id"]

    csrf = login(client, "member")
    missing_csrf = client.post("/api/v1/projects", json={"name": "项目一"})
    assert missing_csrf.status_code == 403

    created = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf},
        json={"name": "项目一"},
    )
    assert created.status_code == 201, created.text


def test_only_super_admin_can_read_other_raw_work_records(api: dict) -> None:
    client: TestClient = api["client"]
    csrf = login(client, "member")
    created = client.post(
        "/api/v1/work-records",
        headers={"X-CSRF-Token": csrf},
        json={
            "work_date": "2026-07-27",
            "content": "完成需求梳理",
            "minutes": 120,
        },
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]

    login(client, "member2")
    assert client.get(f"/api/v1/work-records/{record_id}").status_code == 403
    assert client.get("/api/v1/work-records").json() == []

    login(client, "leader")
    assert client.get(f"/api/v1/work-records/{record_id}").status_code == 403
    assert client.get("/api/v1/work-records").json() == []

    login(client, "admin")
    assert client.get(f"/api/v1/work-records/{record_id}").status_code == 403
    assert client.get("/api/v1/work-records").json() == []
    work_record_audit = client.get(
        "/api/v1/audit-events",
        params={"entity_type": "work_record"},
    )
    assert work_record_audit.status_code == 403

    login(client, "super_admin")
    visible = client.get(f"/api/v1/work-records/{record_id}")
    assert visible.status_code == 200
    assert visible.json()["content"] == "完成需求梳理"
    assert visible.json()["author_id"] == api["users"]["member"]
    assert visible.json()["author_display_name"]
    assert visible.json()["last_editor_display_name"] == visible.json()["author_display_name"]
    assert [item["id"] for item in client.get("/api/v1/work-records").json()] == [record_id]
